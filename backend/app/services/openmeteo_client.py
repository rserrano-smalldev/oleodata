"""Adaptadores REALES de Open-Meteo: histórico (Historical Weather API,
ERA5-Land), elevación y previsión a corto plazo (Forecast API).

Hace peticiones HTTP de verdad a archive-api.open-meteo.com,
api.open-meteo.com/v1/elevation y api.open-meteo.com/v1/forecast. Gratuitas,
sin API key. El histórico usa ERA5-Land (CC BY 4.0, cobertura global desde
1950, resolución de rejilla ~9 km); la previsión usa el modelo por defecto
de Open-Meteo para el punto (normalmente ECMWF/ICON de alta resolución,
hasta 16 días, aquí limitado a `forecast_days_ahead`, 7 por defecto).
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

# La API de previsión no comparte los mismos nombres de capa de humedad de
# suelo que el archivo histórico, y el balance hídrico/los modelos de este
# MVP no la necesitan directamente: se omite en la previsión.
FORECAST_HOURLY_VARS = {
    k: v for k, v in HOURLY_VARS.items() if k != "soil_moisture_7_to_28cm"
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


class OpenMeteoForecastAdapter:
    """adapter_name referenciado en el catálogo (proveedor 'open_meteo_forecast').

    A diferencia del histórico, la previsión es un dato que cambia cada vez
    que se refresca (no tiene sentido acumularla como serie idempotente):
    quien llame a este adaptador debe reemplazar las observaciones antiguas
    de esta fuente, no simplemente insertar encima (ver services/forecast.py).
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def fetch_hourly_forecast(self, lat: float, lon: float, days_ahead: int) -> dict:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(FORECAST_HOURLY_VARS.keys()),
            "forecast_days": days_ahead,
            "timezone": "UTC",
        }
        client = self._client or httpx.AsyncClient(timeout=60)
        owns_client = self._client is None
        try:
            resp = await client.get(settings.open_meteo_forecast_url, params=params)
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns_client:
                await client.aclose()
