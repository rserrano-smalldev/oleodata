import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import WKTElement
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models.catalog import DataProvider, Variable
from app.models.parcel import Parcel
from app.models.timeseries import Observation, Source
from app.models.treatment import Treatment
from app.models.variety import OliveVariety
from app.schemas.discovery import DiscoveryResponse
from app.schemas.parcel import (
    BackfillRequest,
    ParcelCreate,
    ParcelDeleteOut,
    ParcelOut,
    ParcelUpdate,
    ParcelVarietyUpdate,
    SimulateSensorsRequest,
)
from app.schemas.recommendations import RecommendationsOut
from app.schemas.timeseries import DailySeriesOut, DailyVariablePoint
from app.services.agronomy import engine as recommendations_engine
from app.services.backfill import backfill_parcel_era5, sync_parcel_era5
from app.services.daily_series import get_daily_series, get_raw_observations
from app.services.discovery import discover_sources
from app.services.forecast import fetch_and_store_forecast
from app.services.openmeteo_client import fetch_elevation
from app.services.ria_sync import (
    count_cached_ria_stations,
    ensure_ria_stations_cached,
    find_nearby_ria_station,
    sync_parcel_ria,
)
from app.services.simulator import NoHistoryError, simulate_sensor_readings
from app.services.sources import get_or_create_source

from app.api.discovery import candidate_to_out

router = APIRouter(prefix="/v1/parcels", tags=["parcels"])
logger = logging.getLogger(__name__)


async def _get_parcel_or_404(session: AsyncSession, parcel_id: int) -> Parcel:
    parcel = await session.get(Parcel, parcel_id)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcela no encontrada")
    return parcel


def _parcel_to_out(
    parcel: Parcel,
    variety_code: str | None,
    initial_backfill_note: str | None = None,
    ria_note: str | None = None,
) -> ParcelOut:
    return ParcelOut(
        id=parcel.id,
        code=parcel.code,
        name=parcel.name,
        latitude=parcel.latitude,
        longitude=parcel.longitude,
        elevation_m=parcel.elevation_m,
        variety_code=variety_code,
        area_ha=parcel.area_ha,
        field_capacity_mm=parcel.field_capacity_mm,
        sensorization_status=parcel.sensorization_status.value,
        created_at=parcel.created_at,
        initial_backfill_note=initial_backfill_note,
        ria_note=ria_note,
    )


async def _try_auto_ria_sync(session: AsyncSession, parcel: Parcel) -> str | None:
    """Si hay una estación RIA real a menos de `ria_max_distance_km` (15 km
    por defecto), la cachea/usa automáticamente. Nunca falla la creación de
    la parcela si la red de RIA no responde: se degrada a una nota, igual
    que ya se hace con ERA5-Land."""
    try:
        await ensure_ria_stations_cached(session)
        nearby = await find_nearby_ria_station(session, parcel.latitude, parcel.longitude)
        if nearby is None:
            return None
        summary = await sync_parcel_ria(session, parcel, nearby)
        return (
            f"Estación RIA real '{summary.station_name}' (código {summary.station_code}) a "
            f"{summary.horizontal_km:.1f} km: {summary.days_fetched} días de histórico real "
            "importados y usados con prioridad sobre ERA5-Land en las recomendaciones."
        )
    except httpx.HTTPError as exc:
        logger.warning("No se pudo comprobar/sincronizar estaciones RIA para %s: %s", parcel.code, exc)
        return (
            "No se ha podido comprobar si hay una estación RIA cercana (fallo de red). "
            "Usa el botón de sincronizar RIA en el panel de la parcela para reintentarlo."
        )


@router.get("", response_model=list[ParcelOut])
async def list_parcels(session: AsyncSession = Depends(get_session)):
    """No está en la lista mínima del módulo 6, pero sin ella el frontend
    (módulo 7) no tiene forma de listar las parcelas dadas de alta."""
    parcels = (await session.execute(select(Parcel).order_by(Parcel.id))).scalars().all()
    out = []
    for parcel in parcels:
        variety_code = None
        if parcel.variety_id:
            variety = await session.get(OliveVariety, parcel.variety_id)
            variety_code = variety.code if variety else None
        out.append(_parcel_to_out(parcel, variety_code))
    return out


@router.post("", response_model=ParcelOut)
async def create_parcel(payload: ParcelCreate, session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(select(Parcel).where(Parcel.code == payload.code))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe una parcela con código {payload.code!r}")

    variety_id = None
    if payload.variety_code:
        variety = (
            await session.execute(select(OliveVariety).where(OliveVariety.code == payload.variety_code))
        ).scalar_one_or_none()
        if variety is None:
            raise HTTPException(status_code=404, detail=f"Variedad desconocida: {payload.variety_code!r}")
        variety_id = variety.id

    elevation = payload.elevation_m
    if elevation is None:
        try:
            elevation = await fetch_elevation(payload.lat, payload.lon)
        except httpx.HTTPError as exc:
            logger.warning("No se pudo resolver la altitud vía Open-Meteo para %s: %s", payload.code, exc)
            elevation = None

    parcel = Parcel(
        code=payload.code,
        name=payload.name,
        location=WKTElement(f"POINT({payload.lon} {payload.lat})", srid=4326),
        latitude=payload.lat,
        longitude=payload.lon,
        elevation_m=elevation,
        variety_id=variety_id,
        area_ha=payload.area_ha,
        field_capacity_mm=payload.field_capacity_mm,
    )
    session.add(parcel)
    await session.commit()
    await session.refresh(parcel)

    settings = get_settings()
    try:
        summary = await sync_parcel_era5(
            session, parcel, initial_years_back=settings.initial_backfill_years_back
        )
        note = (
            f"Histórico ERA5-Land importado automáticamente: {summary.rows_fetched} lecturas "
            f"horarias reales ({summary.start_date} → {summary.end_date})."
        )
    except httpx.HTTPError as exc:
        logger.warning(
            "No se pudo importar el histórico automático de ERA5-Land para %s: %s", payload.code, exc
        )
        note = (
            "No se ha podido importar el histórico automáticamente (fallo de red con Open-Meteo). "
            "Usa el botón de importar histórico en el panel de la parcela para reintentarlo."
        )

    ria_note = await _try_auto_ria_sync(session, parcel)

    return _parcel_to_out(parcel, payload.variety_code, initial_backfill_note=note, ria_note=ria_note)


@router.get("/{parcel_id}", response_model=ParcelOut)
async def get_parcel(parcel_id: int, session: AsyncSession = Depends(get_session)):
    parcel = await _get_parcel_or_404(session, parcel_id)
    variety_code = None
    if parcel.variety_id:
        variety = await session.get(OliveVariety, parcel.variety_id)
        variety_code = variety.code if variety else None
    return _parcel_to_out(parcel, variety_code)


@router.patch("/{parcel_id}/variety", response_model=ParcelOut)
async def update_parcel_variety(
    parcel_id: int, payload: ParcelVarietyUpdate, session: AsyncSession = Depends(get_session)
):
    """No forma parte de la lista de endpoints del módulo 6, pero el dashboard
    del módulo 7 (comparar el riesgo de repilo cambiando de variedad sobre el
    mismo día simulado) no es posible sin poder reasignar la variedad de una
    parcela ya creada.
    """
    parcel = await _get_parcel_or_404(session, parcel_id)
    variety_code = None
    if payload.variety_code:
        variety = (
            await session.execute(select(OliveVariety).where(OliveVariety.code == payload.variety_code))
        ).scalar_one_or_none()
        if variety is None:
            raise HTTPException(status_code=404, detail=f"Variedad desconocida: {payload.variety_code!r}")
        parcel.variety_id = variety.id
        variety_code = variety.code
    else:
        parcel.variety_id = None

    await session.commit()
    await session.refresh(parcel)
    return _parcel_to_out(parcel, variety_code)


@router.patch("/{parcel_id}", response_model=ParcelOut)
async def update_parcel(parcel_id: int, payload: ParcelUpdate, session: AsyncSession = Depends(get_session)):
    """Edita nombre, variedad, superficie y/o capacidad de campo de una
    parcela ya existente. Lat/lon/elevación son intencionadamente inmutables
    (ver el docstring de `ParcelUpdate`): para eso hay que borrar la parcela
    y darla de alta de nuevo en el sitio correcto.
    """
    parcel = await _get_parcel_or_404(session, parcel_id)
    fields = payload.model_dump(exclude_unset=True)

    if "name" in fields:
        parcel.name = fields["name"]
    if "area_ha" in fields:
        parcel.area_ha = fields["area_ha"]
    if "field_capacity_mm" in fields and fields["field_capacity_mm"] is not None:
        parcel.field_capacity_mm = fields["field_capacity_mm"]
    if "variety_code" in fields:
        if fields["variety_code"]:
            variety = (
                await session.execute(select(OliveVariety).where(OliveVariety.code == fields["variety_code"]))
            ).scalar_one_or_none()
            if variety is None:
                raise HTTPException(status_code=404, detail=f"Variedad desconocida: {fields['variety_code']!r}")
            parcel.variety_id = variety.id
        else:
            parcel.variety_id = None

    await session.commit()
    await session.refresh(parcel)

    variety_code = None
    if parcel.variety_id:
        variety = await session.get(OliveVariety, parcel.variety_id)
        variety_code = variety.code if variety else None
    return _parcel_to_out(parcel, variety_code)


@router.delete("/{parcel_id}", response_model=ParcelDeleteOut)
async def delete_parcel(parcel_id: int, session: AsyncSession = Depends(get_session)):
    """Borra una parcela y todo lo que cuelga de ella: observaciones (real,
    RIA y simulada), las fuentes (`source`) materializadas para ella, y su
    cuaderno de tratamientos. Es destructivo e irreversible — el frontend
    pide confirmación explícita antes de llamar a este endpoint.
    """
    parcel = await _get_parcel_or_404(session, parcel_id)

    source_ids = (
        await session.execute(select(Source.id).where(Source.parcel_id == parcel_id))
    ).scalars().all()
    if source_ids:
        await session.execute(delete(Observation).where(Observation.source_id.in_(source_ids)))
        await session.execute(delete(Source).where(Source.id.in_(source_ids)))
    await session.execute(delete(Treatment).where(Treatment.parcel_id == parcel_id))

    code = parcel.code
    await session.delete(parcel)
    await session.commit()

    return ParcelDeleteOut(deleted=True, code=code)


@router.post("/{parcel_id}/resolve-sources", response_model=DiscoveryResponse)
async def resolve_sources(
    parcel_id: int, dry_run: bool = Query(default=True), session: AsyncSession = Depends(get_session)
):
    parcel = await _get_parcel_or_404(session, parcel_id)
    result = await discover_sources(session, parcel.latitude, parcel.longitude, parcel.elevation_m)

    if not dry_run:
        for candidate in result.candidates:
            if candidate.role is None or not candidate.has_adapter:
                continue
            provider = await session.get(DataProvider, candidate.provider_id)
            await get_or_create_source(
                session,
                provider=provider,
                parcel_id=parcel.id,
                code=f"{candidate.provider_code}:parcel:{parcel.id}",
                is_simulated=(candidate.provider_type == "simulated_sensor"),
                metadata={"role_at_materialization": candidate.role},
            )
        await session.commit()

    return DiscoveryResponse(
        lat=result.lat,
        lon=result.lon,
        elevation_m=result.elevation_m,
        candidates=[candidate_to_out(c) for c in result.candidates],
        coverage_warnings=result.coverage_warnings,
        limitations=result.limitations,
    )


@router.post("/{parcel_id}/backfill")
async def backfill(parcel_id: int, payload: BackfillRequest, session: AsyncSession = Depends(get_session)):
    parcel = await _get_parcel_or_404(session, parcel_id)
    summary = await backfill_parcel_era5(session, parcel, years_back=payload.years_back)
    return {
        "source_id": summary.source_id,
        "start_date": summary.start_date,
        "end_date": summary.end_date,
        "rows_fetched": summary.rows_fetched,
        "chunks": summary.chunks,
        "note": "Histórico REAL de Open-Meteo / ERA5-Land (CC BY 4.0), no simulado.",
    }


@router.post("/{parcel_id}/backfill/sync")
async def backfill_sync(parcel_id: int, session: AsyncSession = Depends(get_session)):
    """Trae solo lo que falta desde el último dato guardado hasta hoy (si la
    parcela no tiene histórico todavía, hace el backfill inicial de
    `initial_backfill_years_back` años, igual que al darla de alta)."""
    parcel = await _get_parcel_or_404(session, parcel_id)
    settings = get_settings()
    summary = await sync_parcel_era5(
        session, parcel, initial_years_back=settings.initial_backfill_years_back
    )
    return {
        "source_id": summary.source_id,
        "start_date": summary.start_date,
        "end_date": summary.end_date,
        "rows_fetched": summary.rows_fetched,
        "chunks": summary.chunks,
        "already_up_to_date": summary.already_up_to_date,
        "note": (
            "Ya estaba al día, no había nada nuevo que importar."
            if summary.already_up_to_date
            else "Histórico REAL de Open-Meteo / ERA5-Land (CC BY 4.0) actualizado hasta hoy."
        ),
    }


@router.post("/{parcel_id}/ria/sync")
async def ria_sync(parcel_id: int, session: AsyncSession = Depends(get_session)):
    """Comprueba (o vuelve a comprobar) si hay una estación RIA real a menos
    de `ria_max_distance_km` (15 km por defecto) y trae/actualiza su
    histórico diario real. A diferencia de ERA5-Land, RIA solo cubre
    Andalucía: si no hay ninguna estación cerca, la respuesta lo declara
    explícitamente en vez de fingir cobertura.
    """
    parcel = await _get_parcel_or_404(session, parcel_id)
    await ensure_ria_stations_cached(session)
    cached_station_count = await count_cached_ria_stations(session)
    nearby = await find_nearby_ria_station(session, parcel.latitude, parcel.longitude)
    if nearby is None:
        # Diagnóstico: aunque no haya ninguna dentro del radio, decir cuál es
        # la más cercana de verdad (sin límite de distancia) ayuda a
        # distinguir "no hay estación cerca" de "algo falla en el cacheado".
        closest_anywhere = await find_nearby_ria_station(
            session, parcel.latitude, parcel.longitude, max_km=100_000
        )
        closest_note = (
            f" La más cercana en toda la caché es '{closest_anywhere.station.name}' "
            f"a {closest_anywhere.horizontal_km:.1f} km."
            if closest_anywhere is not None
            else " No hay ninguna estación RIA cacheada en absoluto."
        )
        return {
            "station_found": False,
            "cached_station_count": cached_station_count,
            "note": (
                "Ninguna estación RIA real a menos de "
                f"{get_settings().ria_max_distance_km:.0f} km de esta parcela "
                f"(RIA solo cubre Andalucía).{closest_note}"
            ),
        }

    try:
        summary = await sync_parcel_ria(session, parcel, nearby)
    except httpx.HTTPError as exc:
        logger.warning(
            "No se pudo traer el histórico de la estación RIA %s para %s: %s",
            nearby.station.code, parcel.code, exc,
        )
        return {
            "station_found": True,
            "cached_station_count": cached_station_count,
            "station_code": nearby.station.code,
            "station_name": nearby.station.name,
            "horizontal_km": round(nearby.horizontal_km, 2),
            "note": (
                f"Se encontró la estación real '{nearby.station.name}' a "
                f"{nearby.horizontal_km:.1f} km, pero no se pudo traer su histórico "
                "diario (fallo de red o de la API de RIA). Reintenta más tarde."
            ),
        }
    return {
        "station_found": True,
        "cached_station_count": cached_station_count,
        "source_id": summary.source_id,
        "station_code": summary.station_code,
        "station_name": summary.station_name,
        "horizontal_km": summary.horizontal_km,
        "start_date": summary.start_date,
        "end_date": summary.end_date,
        "days_fetched": summary.days_fetched,
        "already_up_to_date": summary.already_up_to_date,
        "note": (
            "Ya estaba al día, no había nada nuevo que importar."
            if summary.already_up_to_date
            else f"Histórico diario REAL de la estación RIA importado ({summary.days_fetched} días), "
            "usado con prioridad sobre ERA5-Land en las recomendaciones (estación real > reanálisis). "
            "Si la estación no tenía datos para todo el rango pedido, la sincronización se detiene "
            "pronto en vez de agotar peticiones — repite la llamada más tarde para completar lo que falte."
        ),
    }


@router.post("/{parcel_id}/fetch-forecast")
async def fetch_forecast(parcel_id: int, session: AsyncSession = Depends(get_session)):
    """Trae la previsión REAL de Open-Meteo para los próximos días (por
    defecto `forecast_days_ahead`, 7). Reemplaza la previsión anterior de
    esta parcela por completo: no tiene sentido acumular previsiones viejas.
    """
    parcel = await _get_parcel_or_404(session, parcel_id)
    settings = get_settings()
    summary = await fetch_and_store_forecast(session, parcel, days_ahead=settings.forecast_days_ahead)
    return {
        "source_id": summary.source_id,
        "fetched_at": summary.fetched_at,
        "start": summary.start,
        "end": summary.end,
        "rows_written": summary.rows_written,
        "days_ahead": summary.days_ahead,
        "is_simulated": False,
        "note": (
            "Previsión REAL de Open-Meteo, no histórico ni simulación. Se reemplaza "
            "por completo cada vez que se refresca."
        ),
    }


@router.post("/{parcel_id}/simulate-sensors")
async def simulate_sensors(
    parcel_id: int, payload: SimulateSensorsRequest, session: AsyncSession = Depends(get_session)
):
    parcel = await _get_parcel_or_404(session, parcel_id)

    end = payload.end
    if end is None:
        era5_source = (
            await session.execute(select(Source).where(Source.code == f"era5_land:parcel:{parcel_id}"))
        ).scalar_one_or_none()
        if era5_source is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No hay histórico ERA5-Land descargado para esta parcela. Ejecuta antes "
                    "POST /v1/parcels/{id}/backfill."
                ),
            )
        temp_var = (
            await session.execute(select(Variable.id).where(Variable.code == "temperature_2m"))
        ).scalar_one()
        last_ts = (
            await session.execute(
                select(Observation.timestamp)
                .where(Observation.source_id == era5_source.id)
                .where(Observation.variable_id == temp_var)
                .order_by(Observation.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_ts is None:
            raise HTTPException(status_code=400, detail="Sin observaciones ERA5-Land para esta parcela.")
        end = last_ts

    start = payload.start or (end - timedelta(days=30))

    try:
        summary = await simulate_sensor_readings(session, parcel, start, end)
    except NoHistoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "source_id": summary.source_id,
        "start": summary.start,
        "end": summary.end,
        "sensor_offset_c": round(summary.sensor_offset_c, 3),
        "readings_written": summary.readings_written,
        "interval_minutes": summary.interval_minutes,
        "is_simulated": True,
        "note": (
            "Lecturas 100% SIMULADAS a partir del histórico ERA5-Land — sustituyen a un "
            "sensor físico pendiente de instalación."
        ),
    }


@router.get("/{parcel_id}/observations")
async def raw_observations(
    parcel_id: int,
    provider: str,
    start: datetime,
    end: datetime,
    variables: str = Query(default="temperature_2m,leaf_wetness,precipitation"),
    session: AsyncSession = Depends(get_session),
):
    """No forma parte de la lista mínima del módulo 6: se añade para que el
    frontend (módulo 7) pueda dibujar el detalle horario/15-min del
    simulador, que /daily no ofrece (esa devuelve siempre agregados diarios).
    """
    await _get_parcel_or_404(session, parcel_id)
    variable_codes = [v.strip() for v in variables.split(",") if v.strip()]
    points, is_simulated = await get_raw_observations(session, parcel_id, provider, variable_codes, start, end)
    return {
        "provider": provider,
        "is_simulated": is_simulated,
        "points": [
            {"timestamp": p.timestamp, "variable": p.variable_code, "value": p.value} for p in points
        ],
    }


@router.get("/{parcel_id}/daily", response_model=DailySeriesOut)
async def daily_series(
    parcel_id: int,
    start: date,
    end: date,
    variables: str | None = Query(default=None, description="Códigos de variable separados por coma"),
    session: AsyncSession = Depends(get_session),
):
    parcel = await _get_parcel_or_404(session, parcel_id)

    if variables:
        variable_codes = [v.strip() for v in variables.split(",") if v.strip()]
    else:
        variable_codes = [
            "temperature_2m", "relative_humidity_2m", "precipitation",
            "wind_speed_10m", "shortwave_radiation", "soil_moisture_7_28cm",
            "et0_fao_evapotranspiration", "leaf_wetness",
        ]

    series = await get_daily_series(session, parcel.id, variable_codes, start, end)

    return DailySeriesOut(
        parcel_id=parcel.id,
        start=start,
        end=end,
        variables={
            code: [
                DailyVariablePoint(
                    day=p.day, value=p.value, source_code=p.source_code, is_simulated=p.is_simulated
                )
                for p in points
            ]
            for code, points in series.items()
        },
        notes=[
            "Cuando varias fuentes cubren el mismo día, se usa la de mejor prioridad; "
            "is_simulated indica si esa fuente ganadora es el simulador de sensores (módulo 3)."
        ],
    )


@router.get("/{parcel_id}/recommendations", response_model=RecommendationsOut)
async def recommendations(parcel_id: int, day: date, session: AsyncSession = Depends(get_session)):
    parcel = await _get_parcel_or_404(session, parcel_id)
    if parcel.variety_id:
        await session.refresh(parcel, attribute_names=["variety"])

    try:
        result = await recommendations_engine.build_recommendations(session, parcel, day)
    except recommendations_engine.MissingDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RecommendationsOut(
        day=result.day,
        variety_code=result.variety_code,
        data_basis=result.data_basis,
        threats=result.threats,
        water_balance=result.water_balance,
        not_dynamically_modeled_threats=result.not_dynamically_modeled_threats,
        disclaimer=result.disclaimer,
        warnings=result.warnings,
    )
