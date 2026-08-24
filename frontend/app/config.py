from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_internal_url: str = "http://api:8000"

    # Coordenadas de la finca de referencia usada en todas las pruebas/demo.
    reference_lat: float = 38.521823062719164
    reference_lon: float = -5.159543633627551


@lru_cache
def get_settings() -> Settings:
    return Settings()
