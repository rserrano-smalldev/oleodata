"""RIA (Red de Información Agroclimática de Andalucía): caché de estaciones
reales y sincronización de histórico diario por parcela.

Tres responsabilidades separadas:

- `ensure_ria_stations_cached`: la primera vez que se necesita, trae el
  listado REAL de ~100 estaciones de la API pública de RIA y lo cachea en
  `station` (idempotente vía el UNIQUE (provider_id, code) de bootstrap.py).
  No se vuelve a pedir a la red si ya hay estaciones cacheadas.
- `find_nearby_ria_station`: regla de negocio ESPECÍFICA de RIA pedida por
  el usuario ("estación a menos de 10 km"), distancia puramente horizontal
  (ST_Distance sobre geography), deliberadamente NO la `effective_distance_km`
  ponderada por desnivel que usa el descubrimiento genérico del módulo 2:
  aquí se implementa literalmente el umbral que se pidió, no se reutiliza
  sin más el umbral de otro contexto.
- `sync_parcel_ria`: descarga el histórico diario real de la estación más
  cercana y lo inserta como observaciones. RIA publica agregados DIARIOS
  (mínimo/medio/máximo), no horarios como ERA5-Land o el simulador. Para
  poder reutilizar sin cambios las consultas SQL existentes basadas en
  MIN()/MAX() por día (ver engine.py, daily_series.py), cada día se
  representa con 3 timestamps sintéticos (06:00, 12:00, 18:00 UTC, sin
  relación con la hora real de esos valores):
    - temperatura y humedad relativa: (mínimo, medio, máximo) en esos 3
      instantes, así que MIN()/MAX() por día siguen siendo exactos; la
      media diaria que calcularía un AVG() sobre esos 3 puntos es una
      APROXIMACIÓN (no es exactamente tempMedia/humedadMedia si la
      distribución real no fuera simétrica).
    - viento y precipitación: un único punto a las 12:00 UTC con el valor
      diario (medio o total), ya que ninguna consulta existente necesita su
      mínimo/máximo diario.
  Esta convención se declara aquí y en el README: es una aproximación
  explícita, no un intento de fingir resolución horaria real.

Nota sobre el bug real encontrado y corregido: la primera versión de este
módulo asumía que `latitud`/`longitud` de `estaciones` venían en grados
decimales y hacía `float(valor)` directamente. La API real los da en un
formato empaquetado `"DDMMSSsssH"` (grados-minutos-segundos + hemisferio,
ver `_parse_dmsh_coord` más abajo); `float()` sobre ese texto lanza
ValueError, que quedaba silenciosamente atrapado como "campo incompleto" —
así que NINGUNA estación se llegaba a cachear nunca, y por eso
`find_nearby_ria_station` no encontraba ninguna aunque existiera una
estación real a menos de 10 km (p.ej. IFAPA Hinojosa del Duque, Córdoba).
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import WKTElement

from app.config import get_settings
from app.models.catalog import Station, Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.services.ria_client import RIAAdapter
from app.services.sources import get_or_create_source, get_provider_by_code

logger = logging.getLogger(__name__)

RIA_CHUNK_YEARS = 2  # sin documentación oficial verificada del límite de rango por petición: prudente
RIA_LATENCY_DAYS = 1  # sin confirmar oficialmente cuánto tarda RIA en publicar el día en curso
INSERT_BATCH_SIZE = 5000

HOUR_MIN, HOUR_MID, HOUR_MAX = 6, 12, 18

FIND_NEAREST_RIA_STATION_SQL = text(
    """
    SELECT st.id AS station_id,
           ST_Distance(st.location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 1000.0
               AS horizontal_km
    FROM station st
    JOIN data_provider dp ON dp.id = st.provider_id
    WHERE dp.code = 'ria_andalucia'
      AND ST_DWithin(
            st.location,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :radius_m
      )
    ORDER BY horizontal_km ASC
    LIMIT 1
    """
)


@dataclass
class NearbyStation:
    station: Station
    horizontal_km: float


@dataclass
class RIASyncSummary:
    source_id: int
    station_code: str
    station_name: str
    horizontal_km: float
    start_date: date
    end_date: date
    days_fetched: int
    rows_inserted_or_existing: int
    already_up_to_date: bool = False


_DMSH_PATTERN = re.compile(r"^(\d{2})(\d{2})(\d{5})([NSEW])$")


def _parse_dmsh_coord(raw) -> float:
    """Decodifica una coordenada de `estaciones`.

    Verificado contra el código fuente de `meteospain` (`R/utils.R`,
    `.parse_coords_dmsh`): la API real da `latitud`/`longitud` en un
    formato empaquetado "DDMMSSsssH" — grados (2 dígitos), minutos
    (2 dígitos), segundos×1000 (5 dígitos) y una letra de hemisferio
    N/S/E/W — no en grados decimales. Sur y Oeste son negativos.

    Si el valor no encaja en ese formato exacto, se intenta como grados
    decimales directamente (por si la API cambiara de formato en el
    futuro): no se asume ciegamente un único formato para siempre.
    """
    text_value = str(raw).strip().upper()
    match = _DMSH_PATTERN.match(text_value)
    if match:
        degrees, minutes, sec_thousandths, hemisphere = match.groups()
        value = int(degrees) + int(minutes) / 60 + (int(sec_thousandths) / 1000) / 3600
        return -value if hemisphere in ("S", "W") else value
    return float(text_value)


async def ensure_ria_stations_cached(session: AsyncSession, adapter: RIAAdapter | None = None) -> int:
    """Cachea el listado real de estaciones RIA la primera vez que se necesita.

    Devuelve el número de estaciones cacheadas (existentes si ya lo estaban,
    o recién insertadas). No vuelve a llamar a la red si ya hay alguna fila
    para este proveedor: el listado de estaciones físicas no cambia a diario.
    """
    provider = await get_provider_by_code(session, "ria_andalucia")

    existing_count = (
        await session.execute(
            select(func.count()).select_from(Station).where(Station.provider_id == provider.id)
        )
    ).scalar_one()
    if existing_count > 0:
        return existing_count

    adapter = adapter or RIAAdapter()
    stations = await adapter.fetch_stations()

    rows = []
    for st in stations:
        try:
            lat = _parse_dmsh_coord(st["latitud"])
            lon = _parse_dmsh_coord(st["longitud"])
            codigo = st["codigoEstacion"]
        except (KeyError, TypeError, ValueError):
            logger.warning("Estación RIA con campos incompletos, se ignora: %r", st)
            continue
        altitud = st.get("altitud")
        rows.append(
            {
                "provider_id": provider.id,
                "code": str(codigo),
                "name": st.get("nombre") or f"Estación RIA {codigo}",
                "location": WKTElement(f"POINT({lon} {lat})", srid=4326),
                "elevation_m": float(altitud) if altitud is not None else None,
                "metadata_json": {
                    "provincia_id": st.get("provincia_id"),
                    "provincia_nombre": st.get("provincia_nombre"),
                    "bajoplastico": st.get("bajoplastico"),
                },
            }
        )

    if stations and not rows:
        # Si ninguna estación de una respuesta no vacía se pudo cachear, es
        # casi seguro un bug sistemático de parseo (p.ej. un cambio de
        # formato de coordenadas), no "campos incompletos" puntuales: esto
        # ya ocurrió una vez (ver docstring del módulo) y dejaba a
        # find_nearby_ria_station sin ninguna estación con la que trabajar,
        # sin ningún error visible.
        logger.error(
            "RIA: la API devolvió %d estaciones pero NINGUNA se pudo cachear "
            "(revisar el formato de latitud/longitud, ver _parse_dmsh_coord).",
            len(stations),
        )

    if not rows:
        return 0

    stmt = pg_insert(Station).values(rows).on_conflict_do_nothing(
        index_elements=["provider_id", "code"]
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("RIA: %d estaciones reales cacheadas en `station`.", len(rows))
    return len(rows)


async def find_nearby_ria_station(
    session: AsyncSession, lat: float, lon: float, max_km: float | None = None
) -> NearbyStation | None:
    """Estación RIA real más cercana a (lat, lon), o None si ninguna está a
    menos de `max_km` (por defecto settings.ria_max_distance_km = 10 km).

    Distancia puramente horizontal, deliberadamente sin el ajuste por
    desnivel de `effective_distance_km` (ver docstring del módulo).
    """
    max_km = max_km if max_km is not None else get_settings().ria_max_distance_km
    row = (
        await session.execute(
            FIND_NEAREST_RIA_STATION_SQL, {"lat": lat, "lon": lon, "radius_m": max_km * 1000}
        )
    ).mappings().first()
    if row is None:
        return None
    station = await session.get(Station, row["station_id"])
    return NearbyStation(station=station, horizontal_km=row["horizontal_km"])


def _iter_year_chunks(start: date, end: date, years_per_chunk: int = RIA_CHUNK_YEARS):
    cursor = start
    while cursor <= end:
        chunk_end = min(date(cursor.year + years_per_chunk, cursor.month, 1) - timedelta(days=1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _synthetic_rows_for_day(day: date, fields: dict, variable_ids: dict[str, int], source_id: int) -> list[dict]:
    """Traduce un día de la respuesta diaria de RIA a observaciones sintéticas
    (ver docstring del módulo: 3 puntos min/medio/máx para temp/humedad, 1
    punto al mediodía para viento/precipitación)."""
    rows = []

    def add(hour: int, variable_code: str, value) -> None:
        if value is None:
            return
        rows.append(
            {
                "timestamp": datetime.combine(day, time(hour, 0), tzinfo=timezone.utc),
                "source_id": source_id,
                "variable_id": variable_ids[variable_code],
                "value": float(value),
                "quality_flag": "ok",
            }
        )

    add(HOUR_MIN, "temperature_2m", fields.get("tempMin"))
    add(HOUR_MID, "temperature_2m", fields.get("tempMedia"))
    add(HOUR_MAX, "temperature_2m", fields.get("tempMax"))

    add(HOUR_MIN, "relative_humidity_2m", fields.get("humedadMax"))
    add(HOUR_MID, "relative_humidity_2m", fields.get("humedadMedia"))
    add(HOUR_MAX, "relative_humidity_2m", fields.get("humedadMin"))

    add(HOUR_MID, "wind_speed_10m", fields.get("velViento"))
    add(HOUR_MID, "precipitation", fields.get("precipitacion"))

    return rows


async def _fetch_and_store_ria_range(
    session: AsyncSession,
    source: Source,
    station: Station,
    variable_ids: dict[str, int],
    start_date: date,
    end_date: date,
    adapter: RIAAdapter | None = None,
) -> tuple[int, int]:
    provincia_id = (station.metadata_json or {}).get("provincia_id")
    if provincia_id is None:
        raise ValueError(
            f"Estación RIA {station.code!r} cacheada sin provincia_id: no se puede pedir su histórico."
        )

    adapter = adapter or RIAAdapter()
    total_days = 0
    total_written = 0

    for chunk_start, chunk_end in _iter_year_chunks(start_date, end_date):
        logger.info("RIA source=%s estación=%s: bloque %s -> %s", source.code, station.code, chunk_start, chunk_end)
        daily_rows = await adapter.fetch_daily_range(
            int(provincia_id), int(station.code), chunk_start, chunk_end
        )

        rows = []
        for day_payload in daily_rows:
            fecha = day_payload.get("fecha")
            if not fecha:
                continue
            day = datetime.fromisoformat(str(fecha)[:10]).date()
            rows.extend(_synthetic_rows_for_day(day, day_payload, variable_ids, source.id))
        total_days += len(daily_rows)

        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            batch = rows[i : i + INSERT_BATCH_SIZE]
            if not batch:
                continue
            stmt = pg_insert(Observation).values(batch).on_conflict_do_nothing()
            await session.execute(stmt)
            total_written += len(batch)
        await session.commit()

    return total_days, total_written


async def sync_parcel_ria(
    session: AsyncSession,
    parcel: Parcel,
    nearby: NearbyStation,
    initial_years_back: int | None = None,
    adapter: RIAAdapter | None = None,
) -> RIASyncSummary:
    """Trae solo lo que falta desde el último día guardado hasta hoy, igual
    criterio incremental que `sync_parcel_era5`. Si no hay histórico RIA
    todavía para esta parcela, hace un backfill inicial de
    `initial_years_back` años (por defecto, el mismo que ERA5-Land)."""
    settings = get_settings()
    initial_years_back = initial_years_back or settings.initial_backfill_years_back

    provider = await get_provider_by_code(session, "ria_andalucia")
    source = await get_or_create_source(
        session,
        provider=provider,
        parcel_id=parcel.id,
        code=f"ria_andalucia:parcel:{parcel.id}",
        is_simulated=False,
        metadata={
            "basis": "ria_andalucia",
            "station_id": nearby.station.id,
            "station_code": nearby.station.code,
            "station_name": nearby.station.name,
            "horizontal_km": round(nearby.horizontal_km, 2),
        },
    )
    variable_ids = dict((await session.execute(select(Variable.code, Variable.id))).all())

    end_date = date.today() - timedelta(days=RIA_LATENCY_DAYS)

    last_timestamp = (
        await session.execute(
            select(func.max(Observation.timestamp)).where(
                Observation.source_id == source.id,
                Observation.variable_id == variable_ids["temperature_2m"],
            )
        )
    ).scalar_one_or_none()

    start_date = (
        end_date - timedelta(days=365 * initial_years_back)
        if last_timestamp is None
        else last_timestamp.date() + timedelta(days=1)
    )

    if start_date > end_date:
        return RIASyncSummary(
            source_id=source.id,
            station_code=nearby.station.code,
            station_name=nearby.station.name,
            horizontal_km=round(nearby.horizontal_km, 2),
            start_date=start_date,
            end_date=end_date,
            days_fetched=0,
            rows_inserted_or_existing=0,
            already_up_to_date=True,
        )

    days_fetched, rows_written = await _fetch_and_store_ria_range(
        session, source, nearby.station, variable_ids, start_date, end_date, adapter=adapter
    )

    return RIASyncSummary(
        source_id=source.id,
        station_code=nearby.station.code,
        station_name=nearby.station.name,
        horizontal_km=round(nearby.horizontal_km, 2),
        start_date=start_date,
        end_date=end_date,
        days_fetched=days_fetched,
        rows_inserted_or_existing=rows_written,
    )
