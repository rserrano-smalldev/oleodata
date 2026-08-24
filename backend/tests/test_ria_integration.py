"""Integración RIA (Red de Información Agroclimática de Andalucía):

- caché de estaciones reales (idempotente, sin volver a llamar a la red si
  ya hay estaciones cacheadas)
- regla "estación a menos de 15 km" (distancia puramente horizontal)
- sincronización de histórico diario por parcela, con la convención de 3
  puntos sintéticos por día para temperatura/humedad
- preferencia de RIA sobre ERA5-Land en el motor de recomendaciones cuando
  ambas fuentes cubren el mismo día

No golpea la red real de juntadeandalucia.es (bloqueada desde el sandbox de
desarrollo): se inyecta un RIAAdapter falso con datos de ejemplo.
"""

from datetime import date, timedelta

import httpx
from geoalchemy2 import WKTElement
from sqlalchemy import delete, select

from app.config import get_settings
from app.models.catalog import Station, Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.services.agronomy.engine import build_recommendations
from app.services.backfill import _ensure_era5_source
from app.services.ria_sync import (
    RIA_LATENCY_DAYS,
    NearbyStation,
    _fetch_daily_range_resilient,
    _parse_dmsh_coord,
    ensure_ria_stations_cached,
    find_nearby_ria_station,
    sync_parcel_ria,
)
from app.services.sources import get_provider_by_code

TEST_PARCEL_CODE = "TEST-RIA-INTEGRATION-PARCEL"
# Los Pedroches, Córdoba (misma finca de referencia del README).
PARCEL_LAT, PARCEL_LON = 38.521823062719164, -5.159543633627551

NEAR_STATION_CODE = "TEST-RIA-NEAR"  # a ~2 km del punto de referencia
FAR_STATION_CODE = "TEST-RIA-FAR"  # a >15 km del punto de referencia
# codigoEstacion real de RIA es numérico (ver docstring de ria_client.py): un
# código de test numérico distinto, usado solo por el test de sincronización.
NUMERIC_TEST_STATION_CODE = "9001"
TEST_PROVINCIA_ID = 5  # Córdoba, usada por todos los fixtures de este fichero
OTHER_TEST_PROVINCIA_ID = 14  # provincia distinta, para el test de colisión entre provincias
_PLAIN_TEST_STATION_CODES = [NEAR_STATION_CODE, FAR_STATION_CODE, NUMERIC_TEST_STATION_CODE]
# ensure_ria_stations_cached guarda `code` como "{provincia_id}:{codigoEstacion}"
# (ver services/ria_sync.py: codigoEstacion no es único en toda la red RIA,
# solo dentro de su provincia). Los fixtures que pasan por esa función usan
# el código compuesto; los que construyen Station a mano usan el código
# plano. La limpieza entre tests tiene que borrar ambas formas.
ALL_TEST_STATION_CODES = _PLAIN_TEST_STATION_CODES + [
    f"{TEST_PROVINCIA_ID}:{code}" for code in _PLAIN_TEST_STATION_CODES
] + [f"{OTHER_TEST_PROVINCIA_ID}:{code}" for code in _PLAIN_TEST_STATION_CODES]


class FakeRIAAdapter:
    """Sustituye a RIAAdapter en los tests: nunca llama a la red real."""

    def __init__(self, stations=None, daily_by_station=None):
        self._stations = stations or []
        self._daily_by_station = daily_by_station or {}
        self.fetch_stations_calls = 0
        self.fetch_daily_range_calls = 0

    async def fetch_stations(self):
        self.fetch_stations_calls += 1
        return self._stations

    async def fetch_daily_range(self, provincia_id, codigo_estacion, start_date, end_date):
        self.fetch_daily_range_calls += 1
        return self._daily_by_station.get(codigo_estacion, [])


async def _clean_ria_test_fixtures(session):
    provider = await get_provider_by_code(session, "ria_andalucia")
    station_ids = (
        await session.execute(
            select(Station.id).where(
                Station.provider_id == provider.id,
                Station.code.in_(ALL_TEST_STATION_CODES),
            )
        )
    ).scalars().all()
    if station_ids:
        source_ids = (
            await session.execute(select(Source.id).where(Source.station_id.in_(station_ids)))
        ).scalars().all()
        if source_ids:
            await session.execute(delete(Observation).where(Observation.source_id.in_(source_ids)))
            await session.execute(delete(Source).where(Source.id.in_(source_ids)))
        await session.execute(delete(Station).where(Station.id.in_(station_ids)))
    await session.commit()
    return provider


async def _ensure_test_parcel(session) -> Parcel:
    existing = (
        await session.execute(select(Parcel).where(Parcel.code == TEST_PARCEL_CODE))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    parcel = Parcel(
        code=TEST_PARCEL_CODE,
        name="Parcela de test de integración RIA",
        location=WKTElement(f"POINT({PARCEL_LON} {PARCEL_LAT})", srid=4326),
        latitude=PARCEL_LAT,
        longitude=PARCEL_LON,
        elevation_m=545.0,
    )
    session.add(parcel)
    await session.commit()
    await session.refresh(parcel)
    return parcel


def test_ria_max_distance_default_is_15km():
    """Regresión: el usuario pidió explícitamente ampliar el radio de 10 a
    15 km tras comprobar que la estación real más cercana a la finca de
    referencia quedaba justo fuera de los 10 km."""
    assert get_settings().ria_max_distance_km == 15.0


def test_parse_dmsh_coord_matches_meteospain_formula():
    """La API real de `estaciones` da latitud/longitud en formato empaquetado
    "DDMMSSsssH" (grados, minutos, segundos×1000, hemisferio), NO en grados
    decimales — verificado contra meteospain (R/utils.R, .parse_coords_dmsh).
    Usar float() directamente sobre ese texto (el bug real reportado: RIA
    nunca encontraba ninguna estación, ni siquiera IFAPA Hinojosa del Duque,
    porque ninguna se llegaba a cachear) lanza ValueError; aquí se decodifica
    correctamente.
    """
    # 38°30'18.000" N == 38 + 30/60 + 18/3600 == 38.505
    assert _parse_dmsh_coord("383018000N") == 38.505
    # 5°09'00.000" W == -(5 + 9/60) == -5.15
    assert _parse_dmsh_coord("050900000W") == -5.15
    # Hemisferios N/E positivos, S/W negativos.
    assert _parse_dmsh_coord("100000000E") == 10.0
    assert _parse_dmsh_coord("100000000S") == -10.0

    # Si la API cambiara a grados decimales, no debe romperse: se usan tal cual.
    assert _parse_dmsh_coord("38.521823") == 38.521823
    assert _parse_dmsh_coord(-5.159543633627551) == -5.159543633627551

    # Valores REALES devueltos por la API en producción (estación "Adamuz",
    # Córdoba): confirma el formato contra datos de verdad, no solo contra
    # la fórmula de meteospain.
    assert round(_parse_dmsh_coord("375951000N"), 4) == round(37.9975, 4)
    assert round(_parse_dmsh_coord("042643000W"), 4) == round(-4.445277777777778, 4)


async def test_fetch_daily_range_resilient_splits_on_400_bad_request():
    """Bug real: pedir ~2 años de golpe a datosdiarios da 400 Bad Request (el
    límite real de rango por petición no está documentado). El wrapper debe
    partir el rango en dos y reintentar cada mitad en vez de tirar la
    sincronización entera con un 500."""
    calls = []

    async def fake_fetch(provincia_id, codigo_estacion, start_date, end_date):
        calls.append((start_date, end_date))
        if (end_date - start_date).days > 10:
            request = httpx.Request("GET", "http://test/datosdiarios")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("Bad Request", request=request, response=response)
        return [{"fecha": start_date.isoformat()}]

    class FakeAdapter:
        fetch_daily_range = staticmethod(fake_fetch)

    result = await _fetch_daily_range_resilient(
        FakeAdapter(), 14, 102, date(2020, 1, 1), date(2021, 12, 31)
    )
    assert len(calls) > 1  # tuvo que partir el rango al menos una vez
    assert isinstance(result, list) and len(result) > 0


async def test_ensure_ria_stations_cached_decodes_real_dmsh_coordinate_format(db_session):
    """Reproduce el formato REAL de la API (no el decimal simplificado que
    usan el resto de tests de este fichero) para una estación equivalente a
    IFAPA Hinojosa del Duque (Córdoba, ~38.48 N, 5.14 W): confirma que con el
    parser corregido SÍ se cachea y SÍ se encuentra por proximidad, cerrando
    el bug real reportado por el usuario.
    """
    await _clean_ria_test_fixtures(db_session)

    hinojosa_lat_dmsh = "382852000N"  # 38 + 28/60 + 52/3600 = 38.48111...
    hinojosa_lon_dmsh = "050826000W"  # -(5 + 8/60 + 26/3600) = -5.14055...

    fake = FakeRIAAdapter(
        stations=[
            {
                "codigoEstacion": NEAR_STATION_CODE,
                "nombre": "IFAPA Hinojosa del Duque (test)",
                "provincia": {"id": 5, "nombre": "Córdoba"},
                "altitud": 608,
                "latitud": hinojosa_lat_dmsh,
                "longitud": hinojosa_lon_dmsh,
                "bajoplastico": False,
            }
        ]
    )

    count = await ensure_ria_stations_cached(db_session, adapter=fake)
    assert count == 1

    expected_lat = 38 + 28 / 60 + 52 / 3600
    expected_lon = -(5 + 8 / 60 + 26 / 3600)

    # A ~15 km del punto real, debe encontrarse (la parcela de referencia
    # del README está a pocos km de Hinojosa del Duque).
    nearby = await find_nearby_ria_station(db_session, expected_lat, expected_lon, max_km=1.0)
    assert nearby is not None
    # `code` es compuesto "{provincia_id}:{codigoEstacion}": codigoEstacion
    # solo. es único DENTRO de una provincia (ver bug real documentado en el
    # módulo), así que el código plano ya no basta como clave.
    assert nearby.station.code == f"{TEST_PROVINCIA_ID}:{NEAR_STATION_CODE}"
    assert nearby.station.metadata_json["codigo_estacion"] == NEAR_STATION_CODE
    assert nearby.horizontal_km < 1.0

    await _clean_ria_test_fixtures(db_session)


async def test_ensure_ria_stations_cached_deduplicates_repeated_station_codes(db_session):
    """Reproduce lo observado en producción: la API real de `estaciones`
    devolvió 123 filas pero solo 28 llegaron a `station` — no por un bug de
    parseo (0 descartadas), sino porque varias filas comparten el mismo
    `codigoEstacion` (posiblemente una fila por tipo de dato/resolución
    disponible en esa estación física). El valor devuelto por
    ensure_ria_stations_cached debe reflejar el recuento REAL de filas en
    `station` tras la deduplicación por (provider_id, code), no el número de
    filas candidatas antes de insertar."""
    await _clean_ria_test_fixtures(db_session)

    fake = FakeRIAAdapter(
        stations=[
            {
                "codigoEstacion": NEAR_STATION_CODE,
                "nombre": "Estación de test cercana",
                "provincia": {"id": 5, "nombre": "Córdoba"},
                "altitud": 545,
                "latitud": PARCEL_LAT + 0.01,
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
            {
                # Mismo codigoEstacion que la anterior: fila repetida, como
                # en la respuesta real.
                "codigoEstacion": NEAR_STATION_CODE,
                "nombre": "Estación de test cercana",
                "provincia": {"id": 5, "nombre": "Córdoba"},
                "altitud": 545,
                "latitud": PARCEL_LAT + 0.01,
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
        ]
    )

    count = await ensure_ria_stations_cached(db_session, adapter=fake)
    assert count == 1  # una sola fila física, no 2

    await _clean_ria_test_fixtures(db_session)


async def test_ensure_ria_stations_cached_keeps_same_codigo_estacion_in_different_provinces(db_session):
    """Bug real reportado por el usuario: IFAPA Hinojosa del Duque (provincia
    14, codigoEstacion 102, confirmado en la web oficial de RIA en
    /riaweb/web/estacion/14/102) nunca se cacheaba porque otra estación de
    OTRA provincia también tenía codigoEstacion 102, y `station.code`
    guardaba solo el codigoEstacion — el UNIQUE (provider_id, code)
    descartaba la segunda en silencio. codigoEstacion solo es único DENTRO
    de su provincia, no en toda la red RIA."""
    await _clean_ria_test_fixtures(db_session)

    same_code = "102"
    fake = FakeRIAAdapter(
        stations=[
            {
                "codigoEstacion": same_code,
                "nombre": "Huéneja (otra provincia, mismo código)",
                "provincia": {"id": TEST_PROVINCIA_ID, "nombre": "Córdoba"},
                "altitud": 500,
                "latitud": PARCEL_LAT + 0.01,
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
            {
                "codigoEstacion": same_code,
                "nombre": "IFAPA Hinojosa del Duque (test)",
                "provincia": {"id": OTHER_TEST_PROVINCIA_ID, "nombre": "Córdoba"},
                "altitud": 608,
                "latitud": PARCEL_LAT + 0.02,
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
        ]
    )

    count = await ensure_ria_stations_cached(db_session, adapter=fake)
    assert count == 2  # las DOS deben sobrevivir: son estaciones distintas

    codes = set(
        (
            await db_session.execute(
                select(Station.code).where(
                    Station.code.in_(
                        [f"{TEST_PROVINCIA_ID}:{same_code}", f"{OTHER_TEST_PROVINCIA_ID}:{same_code}"]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert codes == {f"{TEST_PROVINCIA_ID}:{same_code}", f"{OTHER_TEST_PROVINCIA_ID}:{same_code}"}

    await db_session.execute(
        delete(Station).where(
            Station.code.in_([f"{TEST_PROVINCIA_ID}:{same_code}", f"{OTHER_TEST_PROVINCIA_ID}:{same_code}"])
        )
    )
    await db_session.commit()
    await _clean_ria_test_fixtures(db_session)


async def test_ensure_ria_stations_cached_is_idempotent_and_does_not_refetch(db_session):
    provider = await _clean_ria_test_fixtures(db_session)

    fake = FakeRIAAdapter(
        stations=[
            {
                "codigoEstacion": NEAR_STATION_CODE,
                "nombre": "Estación de test cercana",
                "provincia": {"id": 5, "nombre": "Córdoba"},
                "altitud": 545,
                "latitud": PARCEL_LAT + 0.01,  # ~1.1 km al norte
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
            {
                "codigoEstacion": FAR_STATION_CODE,
                "nombre": "Estación de test lejana",
                "provincia": {"id": 5, "nombre": "Córdoba"},
                "altitud": 600,
                "latitud": PARCEL_LAT + 0.2,  # ~22 km al norte
                "longitud": PARCEL_LON,
                "bajoplastico": False,
            },
        ]
    )

    count = await ensure_ria_stations_cached(db_session, adapter=fake)
    assert count >= 2
    assert fake.fetch_stations_calls == 1

    composite_near = f"{TEST_PROVINCIA_ID}:{NEAR_STATION_CODE}"
    composite_far = f"{TEST_PROVINCIA_ID}:{FAR_STATION_CODE}"
    stations = (
        await db_session.execute(
            select(Station).where(
                Station.provider_id == provider.id,
                Station.code.in_([composite_near, composite_far]),
            )
        )
    ).scalars().all()
    assert {s.code for s in stations} == {composite_near, composite_far}
    near = next(s for s in stations if s.code == composite_near)
    assert near.metadata_json["provincia_id"] == 5
    assert near.metadata_json["codigo_estacion"] == NEAR_STATION_CODE
    assert near.elevation_m == 545.0

    # Ya hay estaciones cacheadas para este proveedor: NO debe volver a llamar a fetch_stations.
    fake_should_not_be_called = FakeRIAAdapter(stations=[{"codigoEstacion": "SHOULD-NOT-APPEAR"}])
    count2 = await ensure_ria_stations_cached(db_session, adapter=fake_should_not_be_called)
    assert count2 == count
    assert fake_should_not_be_called.fetch_stations_calls == 0

    await _clean_ria_test_fixtures(db_session)


async def test_find_nearby_ria_station_uses_pure_horizontal_15km_rule(db_session):
    provider = await _clean_ria_test_fixtures(db_session)

    near = Station(
        provider_id=provider.id,
        code=NEAR_STATION_CODE,
        name="Estación de test cercana",
        location=WKTElement(f"POINT({PARCEL_LON} {PARCEL_LAT + 0.01})", srid=4326),
        elevation_m=545.0,
        metadata_json={"provincia_id": 5},
    )
    far = Station(
        provider_id=provider.id,
        code=FAR_STATION_CODE,
        name="Estación de test lejana",
        location=WKTElement(f"POINT({PARCEL_LON} {PARCEL_LAT + 0.2})", srid=4326),
        elevation_m=600.0,
        metadata_json={"provincia_id": 5},
    )
    db_session.add_all([near, far])
    await db_session.commit()

    result = await find_nearby_ria_station(db_session, PARCEL_LAT, PARCEL_LON, max_km=10.0)
    assert result is not None
    assert result.station.code == NEAR_STATION_CODE
    assert result.horizontal_km < 10.0

    # Un punto lejos de ambas estaciones de test: ninguna a menos de 1 km.
    isolated_lat = PARCEL_LAT - 1.0
    result_far_only = await find_nearby_ria_station(db_session, isolated_lat, PARCEL_LON, max_km=1.0)
    assert result_far_only is None

    await _clean_ria_test_fixtures(db_session)


async def test_sync_parcel_ria_writes_synthetic_points_preserving_daily_minmax(db_session):
    provider = await _clean_ria_test_fixtures(db_session)
    parcel = await _ensure_test_parcel(db_session)

    await db_session.execute(
        delete(Station).where(Station.provider_id == provider.id, Station.code == NUMERIC_TEST_STATION_CODE)
    )
    station = Station(
        provider_id=provider.id,
        code=NUMERIC_TEST_STATION_CODE,
        name="Estación de test cercana",
        location=WKTElement(f"POINT({PARCEL_LON} {PARCEL_LAT + 0.01})", srid=4326),
        elevation_m=545.0,
        metadata_json={"provincia_id": 5, "codigo_estacion": int(NUMERIC_TEST_STATION_CODE)},
    )
    db_session.add(station)
    await db_session.commit()
    await db_session.refresh(station)

    # Limpiar cualquier observación de una fuente RIA de esta parcela de pruebas anteriores.
    old_source = (
        await db_session.execute(
            select(Source).where(Source.code == f"ria_andalucia:parcel:{parcel.id}")
        )
    ).scalar_one_or_none()
    if old_source is not None:
        await db_session.execute(delete(Observation).where(Observation.source_id == old_source.id))
        await db_session.execute(delete(Source).where(Source.id == old_source.id))
        await db_session.commit()

    # Exactamente en el último día que sync_parcel_ria puede pedir (hoy -
    # RIA_LATENCY_DAYS): así, tras esta única sincronización, la fuente queda
    # completamente al día y una segunda llamada debe detectarlo sin más red.
    target_day = date.today() - timedelta(days=RIA_LATENCY_DAYS)
    daily_payload = [
        {
            "fecha": target_day.isoformat(),
            "tempMin": 4.0,
            "tempMedia": 12.0,
            "tempMax": 22.0,
            "humedadMin": 30.0,
            "humedadMedia": 55.0,
            "humedadMax": 90.0,
            "velViento": 1.8,
            "precipitacion": 0.0,
        }
    ]

    nearby = NearbyStation(station=station, horizontal_km=1.1)
    fake = FakeRIAAdapter(daily_by_station={int(NUMERIC_TEST_STATION_CODE): daily_payload})

    summary = await sync_parcel_ria(db_session, parcel, nearby, initial_years_back=1, adapter=fake)
    assert summary.already_up_to_date is False
    assert summary.rows_inserted_or_existing > 0

    variable_ids = dict((await db_session.execute(select(Variable.code, Variable.id))).all())

    temp_values = (
        await db_session.execute(
            select(Observation.value)
            .where(Observation.source_id == summary.source_id)
            .where(Observation.variable_id == variable_ids["temperature_2m"])
        )
    ).scalars().all()
    assert min(temp_values) == 4.0
    assert max(temp_values) == 22.0

    humidity_values = (
        await db_session.execute(
            select(Observation.value)
            .where(Observation.source_id == summary.source_id)
            .where(Observation.variable_id == variable_ids["relative_humidity_2m"])
        )
    ).scalars().all()
    assert min(humidity_values) == 30.0
    assert max(humidity_values) == 90.0

    # Segunda llamada: ya está al día (mismo `target_day`, sin más datos que traer).
    summary2 = await sync_parcel_ria(db_session, parcel, nearby, initial_years_back=1, adapter=fake)
    assert summary2.already_up_to_date is True

    await db_session.execute(delete(Observation).where(Observation.source_id == summary.source_id))
    await db_session.execute(delete(Source).where(Source.id == summary.source_id))
    await db_session.execute(delete(Station).where(Station.id == station.id))
    await db_session.commit()
    await _clean_ria_test_fixtures(db_session)


async def test_engine_prefers_ria_over_era5_when_both_cover_the_same_day(db_session):
    provider = await _clean_ria_test_fixtures(db_session)
    parcel = await _ensure_test_parcel(db_session)

    variable_ids = dict((await db_session.execute(select(Variable.code, Variable.id))).all())

    era5_source = await _ensure_era5_source(db_session, parcel)

    station = Station(
        provider_id=provider.id,
        code=NEAR_STATION_CODE,
        name="Estación de test cercana",
        location=WKTElement(f"POINT({PARCEL_LON} {PARCEL_LAT + 0.01})", srid=4326),
        elevation_m=545.0,
        metadata_json={"provincia_id": 5},
    )
    db_session.add(station)
    await db_session.commit()
    await db_session.refresh(station)

    ria_provider = provider
    ria_source = Source(
        provider_id=ria_provider.id,
        station_id=station.id,
        parcel_id=parcel.id,
        code=f"ria_andalucia:parcel:{parcel.id}",
        is_simulated=False,
        metadata_json={"basis": "ria_andalucia"},
    )
    # Limpiar una fuente RIA anterior de esta parcela si existiera (de otro test).
    existing_ria_source = (
        await db_session.execute(select(Source).where(Source.code == ria_source.code))
    ).scalar_one_or_none()
    if existing_ria_source is not None:
        await db_session.execute(delete(Observation).where(Observation.source_id == existing_ria_source.id))
        ria_source = existing_ria_source
    else:
        db_session.add(ria_source)
    await db_session.commit()
    await db_session.refresh(ria_source)

    target_day = date.today() - timedelta(days=10)
    ts_min = ria_sync_utc(target_day, 6)
    ts_max = ria_sync_utc(target_day, 18)

    # ERA5-Land: valores claramente distintos, para poder distinguir cuál gana.
    await db_session.execute(
        delete(Observation).where(
            Observation.source_id == era5_source.id,
            Observation.variable_id == variable_ids["temperature_2m"],
            Observation.timestamp >= ria_sync_utc(target_day, 0),
            Observation.timestamp < ria_sync_utc(target_day + timedelta(days=1), 0),
        )
    )
    db_session.add_all(
        [
            Observation(
                timestamp=ria_sync_utc(target_day, 3),
                source_id=era5_source.id,
                variable_id=variable_ids["temperature_2m"],
                value=1.0,
            ),
            Observation(
                timestamp=ria_sync_utc(target_day, 15),
                source_id=era5_source.id,
                variable_id=variable_ids["temperature_2m"],
                value=99.0,
            ),
        ]
    )

    db_session.add_all(
        [
            Observation(
                timestamp=ts_min,
                source_id=ria_source.id,
                variable_id=variable_ids["temperature_2m"],
                value=4.0,
            ),
            Observation(
                timestamp=ts_max,
                source_id=ria_source.id,
                variable_id=variable_ids["temperature_2m"],
                value=22.0,
            ),
        ]
    )
    await db_session.commit()

    result = await build_recommendations(db_session, parcel, target_day)
    assert result.data_basis == "historico_ria"

    frost_threat = next((t for t in result.threats if t["threat_code"] == "helada"), None)
    assert frost_threat is not None
    # Si hubiera ganado ERA5-Land (1.0 / 99.0), este valor sería distinto de 4.0.
    assert frost_threat["model_detail"]["daily_min_temp_c"] == 4.0

    await db_session.execute(delete(Observation).where(Observation.source_id == ria_source.id))
    await db_session.execute(delete(Source).where(Source.id == ria_source.id))
    await db_session.commit()
    await _clean_ria_test_fixtures(db_session)


def ria_sync_utc(day: date, hour: int):
    from datetime import datetime, time, timezone

    return datetime.combine(day, time(hour, 0), tzinfo=timezone.utc)
