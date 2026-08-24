"""Módulo 2: descarga real del histórico ERA5-Land para una parcela.

Trocea el rango de años en bloques de ~5 años (para evitar timeouts de la API
de Open-Meteo), guarda siempre en UTC, convierte humedad de suelo de
fracción (m3/m3) a porcentaje, e inserta de forma idempotente (ON CONFLICT DO
NOTHING sobre la clave primaria compuesta de `observation`).
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation
from app.services.openmeteo_client import HOURLY_VARS, OpenMeteoERA5LandAdapter
from app.services.sources import get_or_create_source, get_provider_by_code

logger = logging.getLogger(__name__)

CHUNK_YEARS = 5
INSERT_BATCH_SIZE = 5000

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


def _iter_year_chunks(start: date, end: date, years_per_chunk: int = CHUNK_YEARS):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + relativedelta(years=years_per_chunk) - timedelta(days=1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


async def backfill_parcel_era5(
    session: AsyncSession, parcel: Parcel, years_back: int = 25
) -> BackfillSummary:
    provider = await get_provider_by_code(session, "era5_land")

    source = await get_or_create_source(
        session,
        provider=provider,
        parcel_id=parcel.id,
        code=f"era5_land:parcel:{parcel.id}",
        is_simulated=False,
        metadata={"basis": "era5_land", "grid_resolution_km": 9},
    )

    variable_ids = dict(
        (await session.execute(select(Variable.code, Variable.id))).all()
    )

    end_date = date.today() - timedelta(days=6)  # ERA5-Land tiene unos días de latencia
    start_date = end_date - relativedelta(years=years_back)

    adapter = OpenMeteoERA5LandAdapter()

    total_fetched = 0
    total_written = 0
    chunk_count = 0

    for chunk_start, chunk_end in _iter_year_chunks(start_date, end_date):
        chunk_count += 1
        logger.info(
            "Backfill ERA5-Land parcela %s: bloque %s -> %s", parcel.code, chunk_start, chunk_end
        )
        payload = await adapter.fetch_hourly_range(parcel.latitude, parcel.longitude, chunk_start, chunk_end)
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

    return BackfillSummary(
        source_id=source.id,
        start_date=start_date,
        end_date=end_date,
        rows_fetched=total_fetched,
        rows_inserted_or_existing=total_written,
        chunks=chunk_count,
    )
