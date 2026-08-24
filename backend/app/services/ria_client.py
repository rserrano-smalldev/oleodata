"""Adaptador REAL de la Red de Información Agroclimática de Andalucía (RIA),
Consejería de Agricultura de la Junta de Andalucía.

API pública, sin API key. Endpoints verificados contra el código fuente
abierto del paquete R `meteospain` (github.com/emf-creaf/meteospain,
`R/ria_helpers.R`), no inventados: en el momento de escribir esto no fue
posible acceder directamente a la documentación oficial de
juntadeandalucia.es desde este entorno de desarrollo, así que se usó como
referencia técnica un cliente de terceros de código abierto que sí la
documenta con ejemplos de uso reales.

  - Listado de estaciones (todas, con coordenadas):
      GET {base}/agriculturaypesca/ifapa/riaws/estaciones
  - Datos diarios de una estación:
      GET {base}/agriculturaypesca/ifapa/riaws/datosdiarios/forceEt0/
          {provincia_id}/{codigoEstacion}/{fecha_inicio:YYYYMMDD}/{fecha_fin:YYYYMMDD}

IMPORTANTE — qué se mapea y qué no: la respuesta de datos diarios incluye
también `radiacion` y datos de evapotranspiración (de ahí "forceEt0" en la
ruta), pero no ha sido posible verificar sus unidades exactas contra la
documentación oficial desde aquí. Para no inventar una conversión de
unidades, este adaptador NO mapea esos dos campos: solo trae temperatura,
humedad relativa, viento medio y precipitación, que son inequívocos. Antes
de usar radiación/ET0 de RIA en producción, verificar sus unidades contra
la documentación oficial de la Junta de Andalucía.
"""

from datetime import date

import httpx

from app.config import get_settings

RIA_STATIONS_PATH = "/agriculturaypesca/ifapa/riaws/estaciones"


class RIAAdapter:
    """adapter_name referenciado en el catálogo de proveedores (código 'ria_andalucia')."""

    def __init__(self, client: httpx.AsyncClient | None = None, base_url: str | None = None):
        self._client = client
        self._base_url = base_url or get_settings().ria_base_url

    async def fetch_stations(self) -> list[dict]:
        """Devuelve TODAS las estaciones de la red, con sus coordenadas reales.

        Campos esperados por estación (ver docstring del módulo):
        codigoEstacion, nombre, provincia_nombre, provincia_id, altitud,
        longitud, latitud, bajoplastico.
        """
        client = self._client or httpx.AsyncClient(timeout=30)
        owns_client = self._client is None
        try:
            resp = await client.get(f"{self._base_url}{RIA_STATIONS_PATH}")
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns_client:
                await client.aclose()

    async def fetch_daily_range(
        self, provincia_id: int, codigo_estacion: int, start_date: date, end_date: date
    ) -> list[dict]:
        """Datos diarios reales de una estación concreta.

        Campos esperados por día (ver docstring del módulo): fecha, tempMedia,
        tempMin, tempMax, humedadMedia, humedadMin, humedadMax, velViento,
        dirViento, velVientoMax, dirVientoVelMax, precipitacion (+ radiacion
        y ET0, no mapeados, ver docstring del módulo).
        """
        path = (
            f"/agriculturaypesca/ifapa/riaws/datosdiarios/forceEt0/"
            f"{provincia_id}/{codigo_estacion}/"
            f"{start_date.strftime('%Y%m%d')}/{end_date.strftime('%Y%m%d')}"
        )
        client = self._client or httpx.AsyncClient(timeout=60)
        owns_client = self._client is None
        try:
            resp = await client.get(f"{self._base_url}{path}")
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns_client:
                await client.aclose()
