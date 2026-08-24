"""Módulo 6: serie diaria combinando todas las fuentes disponibles de una
parcela según prioridad, con el campo is_simulated marcado por fuente.

Cuando varias fuentes tienen dato para el mismo día y variable, se usa el
valor de la fuente con mejor prioridad (menor data_provider.base_priority);
el resto de fuentes NO se descarta a nivel de base de datos, solo no "gana"
ese día concreto en esta vista agregada.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Variable


@dataclass
class DailyPoint:
    day: date
    value: float
    source_code: str
    is_simulated: bool
    role: str | None = None


SOURCES_FOR_PARCEL_SQL = text(
    """
    SELECT s.id AS source_id, s.code AS source_code, s.is_simulated, dp.base_priority
    FROM source s
    JOIN data_provider dp ON dp.id = s.provider_id
    WHERE s.parcel_id = :parcel_id
    """
)

OBSERVATIONS_SQL = text(
    """
    SELECT (o.timestamp AT TIME ZONE 'UTC')::date AS day, o.source_id, o.value
    FROM observation o
    WHERE o.variable_id = :variable_id
      AND o.source_id = ANY(:source_ids)
      AND o.timestamp >= :start AND o.timestamp < :end
    ORDER BY day
    """
)


def _fold(values: list[float], aggregation_type: str) -> float:
    if aggregation_type == "sum":
        return sum(values)
    if aggregation_type == "min":
        return min(values)
    if aggregation_type == "max":
        return max(values)
    return sum(values) / len(values)  # mean / instant


RAW_OBSERVATIONS_SQL = text(
    """
    SELECT o.timestamp, v.code AS variable_code, o.value
    FROM observation o
    JOIN variable v ON v.id = o.variable_id
    WHERE o.source_id = :source_id
      AND v.code = ANY(:variable_codes)
      AND o.timestamp >= :start AND o.timestamp < :end
    ORDER BY o.timestamp
    """
)


@dataclass
class RawPoint:
    timestamp: datetime
    variable_code: str
    value: float


async def get_raw_observations(
    session: AsyncSession,
    parcel_id: int,
    provider_code: str,
    variable_codes: list[str],
    start: datetime,
    end: datetime,
) -> tuple[list[RawPoint], bool]:
    """Lecturas SIN agregar (resolución nativa de la fuente) para una parcela
    y un proveedor concreto (p.ej. 'sim_sensor_v1' para el detalle horario del
    simulador). Devuelve (puntos, is_simulated) o ([], False) si no hay fuente.
    """
    source_row = (
        await session.execute(
            text("SELECT id, is_simulated FROM source WHERE code = :code"),
            {"code": f"{provider_code}:parcel:{parcel_id}"},
        )
    ).mappings().first()
    if source_row is None:
        return [], False

    rows = (
        await session.execute(
            RAW_OBSERVATIONS_SQL,
            {
                "source_id": source_row["id"],
                "variable_codes": variable_codes,
                "start": start,
                "end": end,
            },
        )
    ).all()
    return [RawPoint(timestamp=r.timestamp, variable_code=r.variable_code, value=r.value) for r in rows], source_row[
        "is_simulated"
    ]


async def get_daily_series(
    session: AsyncSession, parcel_id: int, variable_codes: list[str], start: date, end: date
) -> dict[str, list[DailyPoint]]:
    sources = (
        await session.execute(SOURCES_FOR_PARCEL_SQL, {"parcel_id": parcel_id})
    ).mappings().all()
    if not sources:
        return {code: [] for code in variable_codes}

    source_priority = {row["source_id"]: row["base_priority"] for row in sources}
    source_code_by_id = {row["source_id"]: row["source_code"] for row in sources}
    source_is_simulated = {row["source_id"]: row["is_simulated"] for row in sources}
    source_ids = list(source_priority.keys())

    variables = (
        await session.execute(
            select(Variable.id, Variable.code, Variable.aggregation_type).where(Variable.code.in_(variable_codes))
        )
    ).all()

    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    result: dict[str, list[DailyPoint]] = {}

    for variable_id, code, aggregation_type in variables:
        rows = (
            await session.execute(
                OBSERVATIONS_SQL,
                {"variable_id": variable_id, "source_ids": source_ids, "start": start_dt, "end": end_dt},
            )
        ).all()

        by_day_source: dict[date, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        for day, source_id, value in rows:
            by_day_source[day][source_id].append(value)

        points: list[DailyPoint] = []
        for day in sorted(by_day_source.keys()):
            per_source_values = by_day_source[day]
            best_source_id = min(per_source_values.keys(), key=lambda sid: source_priority[sid])
            folded_value = _fold(per_source_values[best_source_id], aggregation_type.value if hasattr(aggregation_type, "value") else aggregation_type)
            points.append(
                DailyPoint(
                    day=day,
                    value=round(folded_value, 3),
                    source_code=source_code_by_id[best_source_id],
                    is_simulated=source_is_simulated[best_source_id],
                )
            )
        result[code] = points

    return result
