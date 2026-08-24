"""Adaptador REAL de Open-Meteo (Historical Weather API, modelo ERA5-Land).

Es la única fuente climática real de todo el MVP: hace peticiones HTTP de
verdad a archive-api.open-meteo.com y a api.open-meteo.com/v1/elevation.
Gratuita, sin API key, licencia CC BY 4.0, cobertura global desde 1950,
resolución de rejilla ~9 km.
"""

from datetime import date

import httpx

from app.config import get_settings

settings = get_settings()

# Nombres de variable tal como los espera la API de Open-Meteo -> código de
# nuestro catálogo de variables (módulo 1). soil_moisture_7_to_28cm llega en
# fracción m3/m3 y se convierte a porcentaje al insertar (ver backfill.py).
HOURLY_VARS = {
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "relative_humidity_2m",
    "precipitation": "precipitation",
    "wind_speed_10m": "wind_speed_10m",
    "shortwave_radiation": "shortwave_radiation",
    "soil_moisture_7_to_28cm": "soil_moisture_7_28cm",
    "et0_fao_evapotranspiration": "et0_fao_evapotranspiration",
}


async def fetch_elevation(lat: float, lon: float) -> float | None:
    """Consulta la altitud real del punto vía la API de elevación de Open-Meteo.

    Nunca se hardcodea la altitud de ninguna parcela: se resuelve aquí en el
    momento del alta, para cualquier coordenada del planeta.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            settings.open_meteo_elevation_url, params={"latitude": lat, "longitude": lon}
        )
        resp.raise_for_status()
        data = resp.json()
        elevations = data.get("elevation") or []
        return float(elevations[0]) if elevations else None


class OpenMeteoERA5LandAdapter:
    """adapter_name referenciado en el catálogo de proveedores (data_provider.adapter_name)."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def fetch_hourly_range(
        self, lat: float, lon: float, start_date: date, end_date: date
    ) -> dict:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "hourly": ",".join(HOURLY_VARS.keys()),
            "models": "era5_land",
            "timezone": "UTC",
        }
        client = self._client or httpx.AsyncClient(timeout=180)
        owns_client = self._client is None
        try:
            resp = await client.get(settings.open_meteo_archive_url, params=params)
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns_client:
                await client.aclose()
