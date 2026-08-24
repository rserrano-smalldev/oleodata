"""Previsión meteorológica (Open-Meteo Forecast API, real, sin API key).

A diferencia del histórico (`backfill.py`) y del simulador (módulo 3), las
observaciones de previsión son EFÍMERAS: el valor previsto para un mismo
instante futuro cambia según cuándo se consulte, así que no tiene sentido
acumularlas con ON CONFLICT DO NOTHING como el resto de fuentes. Cada
refresco reemplaza por completo las filas anteriores de esta fuente.

Se guardan igualmente en la tabla `observation` (bajo su propio `source`,
`data_provider.type='forecast'`) para poder mostrarlas en tabla/gráfica con
las mismas herramientas que el resto de datos, y para que el motor de
recomendaciones (módulo 4) las use con la misma maquinaria que usa para
ERA5-Land y el simulador.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation
from app.services.openmeteo_client import FORECAST_HOURLY_VARS, OpenMeteoForecastAdapter
from app.services.sources import get_or_create_source, get_provider_by_code

logger = logging.getLogger(__name__)


@dataclass
class ForecastSummary:
    source_id: int
    fetched_at: datetime
    start: datetime | None
    end: datetime | None
    rows_written: int
    days_ahead: int


async def fetch_and_store_forecast(
    session: AsyncSession, parcel: Parcel, days_ahead: int
) -> ForecastSummary:
    provider = await get_provider_by_code(session, "open_meteo_forecast")
    source = await get_or_create_source(
        session,
        provider=provider,
        parcel_id=parcel.id,
        code=f"open_meteo_forecast:parcel:{parcel.id}",
        is_simulated=False,
        metadata={"basis": "open_meteo_forecast"},
    )

    variable_ids = dict((await session.execute(select(Variable.code, Variable.id))).all())

    adapter = OpenMeteoForecastAdapter()
    payload = await adapter.fetch_hourly_forecast(parcel.latitude, parcel.longitude, days_ahead)
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []

    rows = []
    for i, ts_str in enumerate(times):
        timestamp = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        for om_name, variable_code in FORECAST_HOURLY_VARS.items():
            series = hourly.get(om_name)
            if series is None or i >= len(series):
                continue
            value = series[i]
            if value is None:
                continue
            rows.append(
                {
                    "timestamp": timestamp,
                    "source_id": source.id,
                    "variable_id": variable_ids[variable_code],
                    "value": float(value),
                    "quality_flag": "estimated",  # es una previsión, no una medición
                }
            )

    now = datetime.now(timezone.utc)

    # Reemplazo completo de la previsión anterior de esta fuente (ver docstring).
    await session.execute(delete(Observation).where(Observation.source_id == source.id))
    if rows:
        await session.execute(pg_insert(Observation).values(rows))
    await session.commit()

    timestamps = [r["timestamp"] for r in rows]

    return ForecastSummary(
        source_id=source.id,
        fetched_at=now,
        start=min(timestamps) if timestamps else None,
        end=max(timestamps) if timestamps else None,
        rows_written=len(rows),
        days_ahead=days_ahead,
    )
