"""Módulo 2: descarga real del histórico ERA5-Land para una parcela.

Trocea el rango de años en bloques de ~5 años (para evitar timeouts de la API
de Open-Meteo), guarda siempre en UTC, convierte humedad de suelo de
fracción (m3/m3) a porcentaje, e inserta de forma idempotente (ON CONFLICT DO
NOTHING sobre la clave primaria compuesta de `observation`).

Dos formas de traer histórico:

- `backfill_parcel_era5(years_back=N)`: trae explícitamente los últimos N
  años, sea cual sea lo que ya hubiera guardado (vuelve a pedir el rango
  completo; el ON CONFLICT DO NOTHING evita duplicados, pero sí repite
  peticiones HTTP ya hechas antes).
- `sync_parcel_era5(...)`: la variante "trae solo lo que falta". Si la
  parcela no tiene histórico todavía, hace un backfill inicial de
  `initial_years_back` años (por defecto 5, que es lo que se dispara
  automáticamente al dar de alta una parcela). Si ya hay histórico, solo
  pide desde el último día guardado hasta hoy.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.services.openmeteo_client import HOURLY_VARS, OpenMeteoERA5LandAdapter
from app.services.sources import get_or_create_source, get_provider_by_code

logger = logging.getLogger(__name__)

CHUNK_YEARS = 5
INSERT_BATCH_SIZE = 5000
ERA5_LATENCY_DAYS = 6  # ERA5-Land tarda unos días en publicarse

# Conversión de fracción m3/m3 a porcentaje (única variable que lo necesita).
FRACTION_TO_PERCENT_VARS = {"soil_moisture_7_28cm"}


@dataclass
class BackfillSummary:
    source_id: int
    start_date: date
    end_date: date
    rows_fetched: int
    rows_inserted_or_existing: int
    chunks: int
    already_up_to_date: bool = False


def _iter_year_chunks(start: date, end: date, years_per_chunk: int = CHUNK_YEARS):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + relativedelta(years=years_per_chunk) - timedelta(days=1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


async def _fetch_and_store_range(
    session: AsyncSession,
    source: Source,
    variable_ids: dict[str, int],
    lat: float,
    lon: float,
    start_date: date,
    end_date: date,
) -> tuple[int, int, int]:
    """Descarga [start_date, end_date] troceado en bloques de CHUNK_YEARS años
    y lo inserta de forma idempotente. Devuelve (fetched, written, chunks)."""
    adapter = OpenMeteoERA5LandAdapter()
    total_fetched = 0
    total_written = 0
    chunk_count = 0

    for chunk_start, chunk_end in _iter_year_chunks(start_date, end_date):
        chunk_count += 1
        logger.info("ERA5-Land source=%s: bloque %s -> %s", source.code, chunk_start, chunk_end)
        payload = await adapter.fetch_hourly_range(lat, lon, chunk_start, chunk_end)
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []

        rows = []
        for i, ts_str in enumerate(times):
            timestamp = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
            for om_name, variable_code in HOURLY_VARS.items():
                series = hourly.get(om_name)
                if series is None or i >= len(series):
                    continue
                value = series[i]
                if value is None:
                    continue
                if variable_code in FRACTION_TO_PERCENT_VARS:
                    value = value * 100.0
                rows.append(
                    {
                        "timestamp": timestamp,
                        "source_id": source.id,
                        "variable_id": variable_ids[variable_code],
                        "value": float(value),
                        "quality_flag": "ok",
                    }
                )

        total_fetched += len(rows)

        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            batch = rows[i : i + INSERT_BATCH_SIZE]
            if not batch:
                continue
            stmt = pg_insert(Observation).values(batch).on_conflict_do_nothing()
            await session.execute(stmt)
            total_written += len(batch)
        await session.commit()

    return total_fetched, total_written, chunk_count


async def _ensure_era5_source(session: AsyncSession, parcel: Parcel) -> Source:
    provider = await get_provider_by_code(session, "era5_land")
    return await get_or_create_source(
        session,
        provider=provider,
        parcel_id=parcel.id,
        code=f"era5_land:parcel:{parcel.id}",
        is_simulated=False,
        metadata={"basis": "era5_land", "grid_resolution_km": 9},
    )


async def backfill_parcel_era5(
    session: AsyncSession, parcel: Parcel, years_back: int = 25
) -> BackfillSummary:
    """Trae explícitamente los últimos `years_back` años (los vuelve a pedir
    aunque ya estuvieran guardados; útil para profundizar el histórico)."""
    source = await _ensure_era5_source(session, parcel)
    variable_ids = dict((await session.execute(select(Variable.code, Variable.id))).all())

    end_date = date.today() - timedelta(days=ERA5_LATENCY_DAYS)
    start_date = end_date - relativedelta(years=years_back)

    fetched, written, chunks = await _fetch_and_store_range(
        session, source, variable_ids, parcel.latitude, parcel.longitude, start_date, end_date
    )

    return BackfillSummary(
        source_id=source.id,
        start_date=start_date,
        end_date=end_date,
        rows_fetched=fetched,
        rows_inserted_or_existing=written,
        chunks=chunks,
    )


async def sync_parcel_era5(
    session: AsyncSession, parcel: Parcel, initial_years_back: int = 5
) -> BackfillSummary:
    """Trae solo lo que falta desde el último dato guardado hasta hoy.

    Si la parcela no tiene ningún histórico ERA5-Land todavía, hace un
    backfill inicial de `initial_years_back` años (esto es lo que se lanza
    automáticamente al dar de alta la parcela). Si ya había histórico, solo
    pide el hueco entre el último día guardado y hoy.
    """
    source = await _ensure_era5_source(session, parcel)
    variable_ids = dict((await session.execute(select(Variable.code, Variable.id))).all())

    end_date = date.today() - timedelta(days=ERA5_LATENCY_DAYS)

    last_timestamp = (
        await session.execute(
            select(func.max(Observation.timestamp)).where(
                Observation.source_id == source.id,
                Observation.variable_id == variable_ids["temperature_2m"],
            )
        )
    ).scalar_one_or_none()

    if last_timestamp is None:
        start_date = end_date - relativedelta(years=initial_years_back)
    else:
        start_date = last_timestamp.date() + timedelta(days=1)

    if start_date > end_date:
        return BackfillSummary(
            source_id=source.id,
            start_date=start_date,
            end_date=end_date,
            rows_fetched=0,
            rows_inserted_or_existing=0,
            chunks=0,
            already_up_to_date=True,
        )

    fetched, written, chunks = await _fetch_and_store_range(
        session, source, variable_ids, parcel.latitude, parcel.longitude, start_date, end_date
    )

    return BackfillSummary(
        source_id=source.id,
        start_date=start_date,
        end_date=end_date,
        rows_fetched=fetched,
        rows_inserted_or_existing=written,
        chunks=chunks,
    )
