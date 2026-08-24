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
          {provincia_id}/{codigoEstacion}/{fecha_inicio:YYYY-MM-DD}/{fecha_fin:YYYY-MM-DD}

IMPORTANTE — formato de fecha en `datosdiarios`: es `YYYY-MM-DD` CON
GUIONES, no `YYYYMMDD` sin separadores. Una primera versión de este
adaptador asumía `YYYYMMDD` (una lectura demasiado literal del ejemplo de
`meteospain`) y por eso TODAS las peticiones devolvían 400 Bad Request,
sin excepción, para cualquier estación y cualquier rango de fechas — algo
que en su momento se interpretó erróneamente como "huecos reales de la
estación" o "límite de tamaño de rango". El formato real se confirmó
revisando la construcción exacta de la fecha en el código fuente de
`meteospain` (`R/ria_helpers.R`, función `ria_stamp`, que usa
`lubridate::stamp("2001-12-25", ...)` — la plantilla de ejemplo lleva
guiones).

IMPORTANTE — qué se mapea y qué no: la respuesta de datos diarios incluye
también `radiacion` y datos de evapotranspiración (de ahí "forceEt0" en la
ruta), pero no ha sido posible verificar sus unidades exactas contra la
documentación oficial desde aquí. Para no inventar una conversión de
unidades, este adaptador NO mapea esos dos campos: solo trae temperatura,
humedad relativa, viento medio y precipitación, que son inequívocos. Antes
de usar radiación/ET0 de RIA en producción, verificar sus unidades contra
la documentación oficial de la Junta de Andalucía.

IMPORTANTE — formato de coordenadas: `estaciones` NO devuelve `latitud`/
`longitud` en grados decimales, sino como texto empaquetado
`"DDMMSSsssH"` (grados 2 dígitos, minutos 2 dígitos, segundos×1000 en 5
dígitos, y una letra de hemisferio N/S/E/W), verificado en el código fuente
de `meteospain` (`R/utils.R`, función `.parse_coords_dmsh`, autor Rubén F.
Casal) y confirmado contra una respuesta real (p.ej. Adamuz, Córdoba:
`"latitud": "375951000N"`, `"longitud": "042643000W"` → 37.9975 N,
-4.445 W). Este adaptador devuelve esos campos EN CRUDO, tal cual los da la
API (fetch_stations no los convierte): quien los use debe decodificarlos —
ver `app/services/ria_sync.py::_parse_dmsh_coord`, que también acepta
grados decimales por si la API cambia de formato en el futuro.

IMPORTANTE — forma real de cada estación en `estaciones` (confirmada con
una respuesta real, no solo con `meteospain`): la provincia viene ANIDADA,
no como `provincia_id` a nivel superior —

    {
      "provincia": {"id": 14, "nombre": "Córdoba"},
      "codigoEstacion": "2", "nombre": "Adamuz",
      "bajoplastico": false, "activa": true, "visible": true,
      "longitud": "042643000W", "latitud": "375951000N", "altitud": 145,
      "xutm": 373099.0, "yutm": 4206530.0, "huso": 30
    }

`codigoEstacion` **solo es único dentro de su provincia**, no en toda la
red (confirmado: la propia web de RIA direcciona sus estaciones como
`/riaweb/web/estacion/{provincia_id}/{codigoEstacion}`) — dos provincias
distintas pueden tener cada una una estación con el mismo número. Cualquier
código que trate `codigoEstacion` como clave global por sí solo descartará
estaciones reales en silencio (ver `ria_sync.py::ensure_ria_stations_cached`,
que usa el par `(provincia_id, codigoEstacion)` como clave). `activa` y
`visible` no se usan todavía para filtrar el listado (no se ha verificado
qué significan exactamente); `xutm`/`yutm`/`huso` (coordenadas UTM
alternativas) tampoco se usan, solo `latitud`/`longitud`.
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

        Campos esperados por estación (ver docstring del módulo, con la forma
        real completa): codigoEstacion, nombre, provincia (anidado, con id y
        nombre), altitud, longitud, latitud, bajoplastico, activa, visible.
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
            f"{start_date.isoformat()}/{end_date.isoformat()}"
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
