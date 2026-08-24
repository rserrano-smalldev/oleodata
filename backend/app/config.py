from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://oleodata:oleodata_dev_password@db:5432/oleodata"
    )
    admin_username: str = "admin"
    admin_password: str = "changeme_admin_password"

    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_elevation_url: str = "https://api.open-meteo.com/v1/elevation"
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"

    # Años de histórico que se importan automáticamente al dar de alta una
    # parcela. El resto del histórico (hasta el máximo razonable, ~25 años)
    # se trae bajo demanda con /backfill.
    initial_backfill_years_back: int = 5

    # Días de previsión meteorológica que se traen de Open-Meteo Forecast API.
    forecast_days_ahead: int = 7

    # Radio de búsqueda de estaciones para el descubrimiento de fuentes (módulo 2)
    discovery_station_radius_km: float = 50.0
    discovery_needs_review_elevation_diff_m: float = 150.0
    discovery_needs_review_horizontal_km: float = 25.0

    # Variables consideradas críticas para los modelos agronómicos: si ninguna
    # fuente descubierta las cubre, la API debe declararlo explícitamente.
    critical_variable_codes: tuple[str, ...] = (
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "leaf_wetness",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
