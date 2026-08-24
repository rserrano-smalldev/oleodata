"""Módulo 3 — SIMULADOR DE SENSORES.

No hay sensores físicos en este MVP. Este módulo genera lecturas SINTÉTICAS
de sensor de parcela a partir del histórico REAL de ERA5-Land ya descargado
(módulo 2), nunca de ruido aleatorio desconectado de la realidad climática:

  - temperature_2m: interpola linealmente la temperatura horaria real de
    ERA5-Land a pasos de 15 minutos, y le añade (a) un sesgo fijo por sensor
    (-0.8..+0.8 °C, generado una vez y persistido en la metadata de la
    fuente — simula el microclima real dentro de la parcela) y (b) ruido de
    alta frecuencia ±0.3 °C en cada lectura (simula el ruido de instrumento).

  - leaf_wetness (humectación foliar): NINGUNA red pública mide esta
    variable. Se deriva con un modelo explícito y aproximado: la
    humectación sube cuando la humedad relativa de ERA5 supera ~90 % o hay
    precipitación (proxy de rocío/niebla/lluvia), y decae con la radiación
    solar y el viento (secado). Es una APROXIMACIÓN, no una medición real,
    y se marca como tal en todo momento (is_simulated=True a nivel de
    fuente, igual que el resto de variables de este simulador).

  - precipitation: NO se deriva suavemente de ERA5 (que ya es de por sí el
    dato menos fiable de ERA5-Land por ser un fenómeno local). Se simula un
    pluviómetro de cazoletas real: la cantidad total del día se reparte en
    pulsos discretos de 0.2 mm entre las horas en que ERA5 marca
    precipitación horaria > 0, con variación aleatoria en el reparto.

Todo esto se guarda bajo un `source` cuyo proveedor es de tipo
'simulated_sensor', NUNCA reutilizando el source_id del reanálisis real.
"""

import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.services.agronomy.leaf_wetness_model import compute_hourly_wetness
from app.services.sources import get_or_create_source, get_provider_by_code

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_MINUTES = 15
TEMPERATURE_OFFSET_RANGE_C = (-0.8, 0.8)
TEMPERATURE_NOISE_RANGE_C = (-0.3, 0.3)
RAIN_TIP_MM = 0.2


class NoHistoryError(ValueError):
    """El simulador depende del histórico ERA5-Land ya descargado (módulo 2)."""


@dataclass
class SimulationSummary:
    source_id: int
    parcel_id: int
    start: datetime
    end: datetime
    sensor_offset_c: float
    readings_written: int
    interval_minutes: int = SAMPLE_INTERVAL_MINUTES


async def _load_era5_hourly_series(
    session: AsyncSession, era5_source: Source, start: datetime, end: datetime
) -> dict[str, dict[datetime, float]]:
    variable_rows = (await session.execute(select(Variable.id, Variable.code))).all()
    variable_code_by_id = dict(variable_rows)

    rows = (
        await session.execute(
            select(Observation.timestamp, Observation.variable_id, Observation.value)
            .where(Observation.source_id == era5_source.id)
            .where(Observation.timestamp >= start - timedelta(hours=2))
            .where(Observation.timestamp <= end + timedelta(hours=2))
            .order_by(Observation.timestamp)
        )
    ).all()

    series: dict[str, dict[datetime, float]] = defaultdict(dict)
    for ts, variable_id, value in rows:
        code = variable_code_by_id.get(variable_id)
        if code:
            series[code][ts] = value
    return series


def _interp_series(series: dict[datetime, float], targets: list[datetime]) -> np.ndarray:
    if not series:
        return np.full(len(targets), np.nan)
    xs = sorted(series.keys())
    x_epoch = np.array([t.timestamp() for t in xs])
    y = np.array([series[t] for t in xs])
    t_epoch = np.array([t.timestamp() for t in targets])
    return np.interp(t_epoch, x_epoch, y)


def _simulate_rain_pulses(
    precip_hourly: dict[datetime, float], rng: random.Random
) -> dict[datetime, float]:
    """Pluviómetro de cazoletas simulado: pulsos discretos de 0.2 mm.

    Reparte el total diario en pulsos entre las horas con precipitación
    horaria > 0 según ERA5, con variación aleatoria en el reparto (elección
    ponderada de la hora de cada pulso + minuto exacto dentro de la hora).
    """
    by_day: dict[date, dict[datetime, float]] = defaultdict(dict)
    for hour, mm in precip_hourly.items():
        if mm and mm > 0:
            by_day[hour.date()][hour] = mm

    pulses: dict[datetime, float] = defaultdict(float)
    for day, hour_map in by_day.items():
        day_total_mm = sum(hour_map.values())
        n_tips = round(day_total_mm / RAIN_TIP_MM)
        if n_tips <= 0:
            continue
        wet_hours = list(hour_map.keys())
        weights = [hour_map[h] for h in wet_hours]
        for _ in range(n_tips):
            hour = rng.choices(wet_hours, weights=weights, k=1)[0]
            slot = hour + timedelta(minutes=SAMPLE_INTERVAL_MINUTES * rng.randrange(4))
            pulses[slot] += RAIN_TIP_MM
    return dict(pulses)


async def simulate_sensor_readings(
    session: AsyncSession, parcel: Parcel, start: datetime, end: datetime
) -> SimulationSummary:
    era5_source = (
        await session.execute(
            select(Source).where(Source.code == f"era5_land:parcel:{parcel.id}")
        )
    ).scalar_one_or_none()
    if era5_source is None:
        raise NoHistoryError(
            "No hay histórico ERA5-Land descargado para esta parcela. El simulador de "
            "sensores parte de ese histórico como base: ejecuta antes "
            "POST /v1/parcels/{id}/backfill."
        )

    era5_series = await _load_era5_hourly_series(session, era5_source, start, end)
    temp_series = era5_series.get("temperature_2m", {})
    if not temp_series:
        raise NoHistoryError(
            "No hay observaciones ERA5-Land de temperatura en el rango solicitado. "
            "Ejecuta antes POST /v1/parcels/{id}/backfill para este periodo."
        )

    wetness_hourly = compute_hourly_wetness(
        rh_series=era5_series.get("relative_humidity_2m", {}),
        precip_series=era5_series.get("precipitation", {}),
        radiation_series=era5_series.get("shortwave_radiation", {}),
        wind_series=era5_series.get("wind_speed_10m", {}),
    )

    sim_provider = await get_provider_by_code(session, "sim_sensor_v1")
    sim_source_code = f"sim_sensor_v1:parcel:{parcel.id}"
    rng = random.Random()
    existing_sim_source = (
        await session.execute(select(Source).where(Source.code == sim_source_code))
    ).scalar_one_or_none()
    if existing_sim_source is not None:
        offset_c = existing_sim_source.metadata_json.get("offset_c")
        if offset_c is None:
            offset_c = rng.uniform(*TEMPERATURE_OFFSET_RANGE_C)
        sim_source = existing_sim_source
    else:
        offset_c = rng.uniform(*TEMPERATURE_OFFSET_RANGE_C)
        sim_source = await get_or_create_source(
            session,
            provider=sim_provider,
            parcel_id=parcel.id,
            code=sim_source_code,
            is_simulated=True,
            metadata={
                "simulated": True,
                "basis": "era5_land",
                "purpose": "MVP demo — sustituye a sensor físico pendiente de instalación",
                "offset_c": offset_c,
            },
        )
        await session.flush()

    targets: list[datetime] = []
    cursor = start
    while cursor <= end:
        targets.append(cursor)
        cursor += timedelta(minutes=SAMPLE_INTERVAL_MINUTES)

    temp_interp = _interp_series(temp_series, targets)
    wetness_interp = _interp_series(wetness_hourly, targets)
    rain_pulses = _simulate_rain_pulses(era5_series.get("precipitation", {}), rng)

    variable_ids = dict((await session.execute(select(Variable.code, Variable.id))).all())

    rows = []
    for i, ts in enumerate(targets):
        noise = rng.uniform(*TEMPERATURE_NOISE_RANGE_C)
        sim_temp = float(temp_interp[i]) + offset_c + noise
        rows.append(
            {
                "timestamp": ts,
                "source_id": sim_source.id,
                "variable_id": variable_ids["temperature_2m"],
                "value": sim_temp,
                "quality_flag": "ok",
            }
        )

        wetness_value = float(np.clip(wetness_interp[i], 0.0, 1.0))
        rows.append(
            {
                "timestamp": ts,
                "source_id": sim_source.id,
                "variable_id": variable_ids["leaf_wetness"],
                "value": wetness_value,
                "quality_flag": "estimated",
            }
        )

        precip_value = rain_pulses.get(ts, 0.0)
        rows.append(
            {
                "timestamp": ts,
                "source_id": sim_source.id,
                "variable_id": variable_ids["precipitation"],
                "value": precip_value,
                "quality_flag": "ok",
            }
        )

    written = 0
    batch_size = 3000
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        stmt = pg_insert(Observation).values(batch).on_conflict_do_nothing()
        await session.execute(stmt)
        written += len(batch)
    await session.commit()

    return SimulationSummary(
        source_id=sim_source.id,
        parcel_id=parcel.id,
        start=start,
        end=end,
        sensor_offset_c=offset_c,
        readings_written=written,
    )
