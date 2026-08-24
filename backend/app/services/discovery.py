"""Módulo 2: descubrimiento de fuentes climáticas por coordenadas.

Dado un punto (lat, lon, altitud), decide qué proveedores de datos lo cubren,
los puntúa y les asigna un rol (primary/secondary/backfill/fallback). Es
agnóstico de región: funciona igual para cualquier punto del planeta, la
única razón por la que en este MVP siempre gana ERA5-Land es que es el único
proveedor con adaptador implementado y cobertura global.
"""

from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.catalog import Variable

settings = get_settings()

EFFECTIVE_KM_WEIGHT = 1.0
PRIORITY_WEIGHT = 1.0
HISTORY_BONUS_WEIGHT_PER_YEAR = 0.1
HISTORY_BONUS_MAX_YEARS = 25
COMPLETENESS_BONUS_WEIGHT = 5.0

STATION_CANDIDATES_SQL = text(
    """
    SELECT DISTINCT ON (dp.id)
        dp.id AS provider_id, dp.code AS provider_code, dp.name AS provider_name,
        dp.type AS provider_type, dp.base_priority, dp.has_adapter,
        dp.variables_supported, dp.notes,
        st.id AS station_id, st.code AS station_code, st.name AS station_name,
        ST_Distance(st.location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 1000.0
            AS horizontal_km,
        abs(coalesce(st.elevation_m, 0) - :elevation) AS elevation_diff_m,
        effective_distance_km(
            ST_Distance(st.location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) / 1000.0,
            abs(coalesce(st.elevation_m, 0) - :elevation)
        ) AS effective_km
    FROM data_provider dp
    JOIN station st ON st.provider_id = dp.id
    WHERE dp.type = 'station_network'
      AND ST_DWithin(
            st.location,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :radius_m
      )
    ORDER BY dp.id, effective_km ASC
    """
)

REANALYSIS_CANDIDATES_SQL = text(
    """
    SELECT dp.id AS provider_id, dp.code AS provider_code, dp.name AS provider_name,
           dp.type AS provider_type, dp.base_priority, dp.has_adapter,
           dp.variables_supported, dp.notes
    FROM data_provider dp
    WHERE dp.type = 'reanalysis'
      AND (
          dp.coverage_geom IS NULL
          OR ST_Covers(dp.coverage_geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
      )
    """
)

# Proveedores catalogados pero sin adaptador (para que la respuesta declare
# explícitamente qué falta por integrar, sin fingir que cubren el punto).
UNIMPLEMENTED_CANDIDATES_SQL = text(
    """
    SELECT dp.id AS provider_id, dp.code AS provider_code, dp.name AS provider_name,
           dp.type AS provider_type, dp.base_priority, dp.has_adapter,
           dp.variables_supported, dp.notes
    FROM data_provider dp
    WHERE dp.has_adapter = FALSE
      AND dp.type IN ('station_network', 'reanalysis')
    """
)


@dataclass
class SourceCandidate:
    provider_id: int
    provider_code: str
    provider_name: str
    provider_type: str
    base_priority: int
    has_adapter: bool
    variables_supported: list[str]
    horizontal_km: float | None
    elevation_diff_m: float | None
    effective_km: float | None
    history_years: float = 0.0
    completeness_ratio: float = 0.0
    station_id: int | None = None
    station_code: str | None = None
    station_name: str | None = None
    score: float = field(init=False, default=0.0)
    needs_review: bool = False
    review_reason: str | None = None
    role: str | None = None
    notes: str | None = None

    def compute_score(self) -> None:
        if self.effective_km is None:
            self.score = float("inf")
            return
        bonus = (
            min(self.history_years, HISTORY_BONUS_MAX_YEARS) * HISTORY_BONUS_WEIGHT_PER_YEAR
            + self.completeness_ratio * COMPLETENESS_BONUS_WEIGHT
        )
        self.score = (
            EFFECTIVE_KM_WEIGHT * self.effective_km + PRIORITY_WEIGHT * self.base_priority - bonus
        )


@dataclass
class DiscoveryResult:
    lat: float
    lon: float
    elevation_m: float | None
    candidates: list[SourceCandidate]
    coverage_warnings: list[str]
    limitations: list[str]


async def discover_sources(
    session: AsyncSession, lat: float, lon: float, elevation_m: float | None
) -> DiscoveryResult:
    elevation = elevation_m if elevation_m is not None else 0.0

    station_rows = (
        await session.execute(
            STATION_CANDIDATES_SQL,
            {"lat": lat, "lon": lon, "elevation": elevation, "radius_m": settings.discovery_station_radius_km * 1000},
        )
    ).mappings().all()

    reanalysis_rows = (
        await session.execute(REANALYSIS_CANDIDATES_SQL, {"lat": lat, "lon": lon})
    ).mappings().all()

    unimplemented_rows = (await session.execute(UNIMPLEMENTED_CANDIDATES_SQL)).mappings().all()
    unimplemented_by_provider = {row["provider_id"]: row for row in unimplemented_rows}

    candidates: list[SourceCandidate] = []

    for row in station_rows:
        c = SourceCandidate(
            provider_id=row["provider_id"],
            provider_code=row["provider_code"],
            provider_name=row["provider_name"],
            provider_type=row["provider_type"],
            base_priority=row["base_priority"],
            has_adapter=row["has_adapter"],
            variables_supported=list(row["variables_supported"] or []),
            horizontal_km=row["horizontal_km"],
            elevation_diff_m=row["elevation_diff_m"],
            effective_km=row["effective_km"],
            station_id=row["station_id"],
            station_code=row["station_code"],
            station_name=row["station_name"],
            notes=row["notes"],
        )
        if (
            row["elevation_diff_m"] > settings.discovery_needs_review_elevation_diff_m
            or row["horizontal_km"] > settings.discovery_needs_review_horizontal_km
        ):
            c.needs_review = True
            c.review_reason = (
                "Desnivel u distancia horizontal frente a la estación superan el umbral "
                "de confianza automática. El sistema NO evalúa barreras orográficas "
                "intermedias entre el punto y la estación: revisar manualmente antes "
                "de activar esta fuente."
            )
        # Se ha encontrado una estación real -> este proveedor ya no es "no cubierto".
        unimplemented_by_provider.pop(row["provider_id"], None)
        candidates.append(c)

    for row in reanalysis_rows:
        candidates.append(
            SourceCandidate(
                provider_id=row["provider_id"],
                provider_code=row["provider_code"],
                provider_name=row["provider_name"],
                provider_type=row["provider_type"],
                base_priority=row["base_priority"],
                has_adapter=row["has_adapter"],
                variables_supported=list(row["variables_supported"] or []),
                horizontal_km=0.0,
                elevation_diff_m=0.0,
                effective_km=0.0,
                notes=row["notes"],
            )
        )

    for c in candidates:
        c.compute_score()

    usable = sorted(
        (c for c in candidates if c.has_adapter and not c.needs_review),
        key=lambda c: c.score,
    )

    if usable:
        primary = usable[0]
        primary.role = "primary"
        covered = set(primary.variables_supported)
        for c in usable[1:]:
            new_vars = set(c.variables_supported) - covered
            if new_vars:
                c.role = "secondary"
                covered |= new_vars
            else:
                c.role = "fallback"

    limitations = [
        "El descubrimiento de estaciones no evalúa barreras orográficas intermedias "
        "entre el punto y la estación: el desnivel es una aproximación por diferencia "
        "de altitud, no un perfil real del terreno.",
        "ERA5-Land tiene una resolución de rejilla de ~9 km: el valor se interpola al "
        "punto exacto, pero microclimas más finos que esa rejilla no se capturan.",
        "En este MVP no hay ninguna red de estaciones regional con adaptador "
        "implementado (AEMET/SIAR/RIA quedan catalogadas pero inactivas).",
    ]

    variable_rows = (
        await session.execute(select(Variable.code, Variable.name))
    ).all()
    variable_names = dict(variable_rows)

    usable_variable_union: set[str] = set()
    for c in candidates:
        if c.has_adapter and not c.needs_review:
            usable_variable_union |= set(c.variables_supported)

    coverage_warnings = []
    for code in settings.critical_variable_codes:
        if code not in usable_variable_union:
            name = variable_names.get(code, code)
            coverage_warnings.append(f"sin cobertura para: {name} — se recomienda sensor propio")

    # Proveedores sin adaptador que ni siquiera llegaron a la fase de candidatos
    # (p.ej. sin ninguna estación a menos de 50 km): se listan igualmente como
    # "sin adaptador implementado", no se ocultan.
    for row in unimplemented_by_provider.values():
        candidates.append(
            SourceCandidate(
                provider_id=row["provider_id"],
                provider_code=row["provider_code"],
                provider_name=row["provider_name"],
                provider_type=row["provider_type"],
                base_priority=row["base_priority"],
                has_adapter=False,
                variables_supported=list(row["variables_supported"] or []),
                horizontal_km=None,
                elevation_diff_m=None,
                effective_km=None,
                notes=(row["notes"] or "") + " Sin estación conocida a menos de "
                f"{settings.discovery_station_radius_km:.0f} km de este punto.",
            )
        )

    return DiscoveryResult(
        lat=lat,
        lon=lon,
        elevation_m=elevation_m,
        candidates=candidates,
        coverage_warnings=coverage_warnings,
        limitations=limitations,
    )
