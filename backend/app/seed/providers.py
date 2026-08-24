"""Catálogo de proveedores de datos.

Solo `era5_land` y `sim_sensor_v1` tienen adaptador implementado en este MVP
(has_adapter=True). Las redes regionales reales (AEMET, SIAR, RIA/RAIF) están
catalogadas para que la arquitectura de descubrimiento las tenga en cuenta el
día que se implemente su adaptador, pero hoy no aportan ningún dato: no se
inventan estaciones ni lecturas para ellas.
"""

PROVIDERS = [
    {
        "code": "era5_land",
        "name": "Open-Meteo Historical Weather API (ERA5-Land)",
        "type": "reanalysis",
        "coverage_geom": None,  # cobertura global
        "base_priority": 50,
        "adapter_name": "app.services.openmeteo_client.OpenMeteoERA5LandAdapter",
        "has_adapter": True,
        "variables_supported": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "shortwave_radiation",
            "soil_moisture_7_28cm",
            "et0_fao_evapotranspiration",
        ],
        "license": "CC BY 4.0",
        "notes": (
            "Reanálisis ERA5-Land, resolución ~9 km, histórico desde 1950, sin API "
            "key. Única fuente climática REAL de este MVP. No mide humectación "
            "foliar."
        ),
    },
    {
        "code": "aemet_stations",
        "name": "Red de estaciones AEMET",
        "type": "station_network",
        "coverage_geom": None,
        "base_priority": 10,
        "adapter_name": None,
        "has_adapter": False,
        "variables_supported": ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"],
        "license": None,
        "notes": "Sin adaptador implementado en este MVP. Catalogado para no requerir migración futura.",
    },
    {
        "code": "siar_stations",
        "name": "Red SIAR (agroclimática, MAPA)",
        "type": "station_network",
        "coverage_geom": None,
        "base_priority": 15,
        "adapter_name": None,
        "has_adapter": False,
        "variables_supported": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "et0_fao_evapotranspiration",
        ],
        "license": None,
        "notes": "Sin adaptador implementado en este MVP. Catalogado para no requerir migración futura.",
    },
    {
        "code": "ria_andalucia",
        "name": "Red de Información Agroclimática de Andalucía / RIA (Junta de Andalucía)",
        "type": "station_network",
        "coverage_geom": None,  # determinado en la práctica por las estaciones reales cacheadas
        "base_priority": 12,  # mejor prioridad que era5_land (50): estación real > reanálisis
        "adapter_name": "app.services.ria_client.RIAAdapter",
        "has_adapter": True,
        "variables_supported": ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"],
        "license": None,
        "notes": (
            "API REST real y pública de la Junta de Andalucía (~100 estaciones), sin API key. "
            "No mide humectación foliar. La API también ofrece radiación y ET0 (ruta "
            "'forceEt0') pero no se han podido verificar sus unidades desde este entorno de "
            "desarrollo: no se mapean, para no inventar una conversión. El balance hídrico "
            "sigue usando ET0 de ERA5-Land/previsión aunque la parcela tenga estación RIA "
            "cerca. Solo se usa automáticamente para una parcela si hay una estación real a "
            "menos de 15 km (ver app/services/ria_sync.py)."
        ),
    },
    {
        "code": "open_meteo_forecast",
        "name": "Open-Meteo Forecast API (previsión a corto plazo)",
        "type": "forecast",
        "coverage_geom": None,  # cobertura global
        # Peor prioridad que ERA5-Land (50): en el raro caso de solape de un
        # día entre histórico ya publicado y previsión ya descargada, debe
        # ganar siempre el dato histórico confirmado, nunca una previsión.
        "base_priority": 55,
        "adapter_name": "app.services.openmeteo_client.OpenMeteoForecastAdapter",
        "has_adapter": True,
        "variables_supported": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "shortwave_radiation",
            "et0_fao_evapotranspiration",
        ],
        "license": "CC BY 4.0",
        "notes": (
            "Previsión meteorológica REAL (no reanálisis, no histórico): los valores de "
            "días futuros cambian cada vez que se refresca, por lo que sus observaciones "
            "se reemplazan en cada actualización en vez de acumularse. Usada solo para "
            "recomendaciones de los próximos días (ver módulo de previsión), nunca para "
            "reconstruir histórico."
        ),
    },
    {
        "code": "sim_sensor_v1",
        "name": "Simulador de sensor de parcela (puente hasta hardware real)",
        "type": "simulated_sensor",
        "coverage_geom": None,
        "base_priority": 5,
        "adapter_name": "app.services.simulator.SyntheticSensorAdapter",
        "has_adapter": True,
        "variables_supported": ["temperature_2m", "precipitation", "leaf_wetness"],
        "license": None,
        "notes": (
            "100% SIMULADO. Sustituye a un sensor físico pendiente de instalación. "
            "No participa en el descubrimiento automático de fuentes climáticas "
            "(módulo 2): se activa explícitamente por parcela vía "
            "/v1/parcels/{id}/simulate-sensors."
        ),
    },
]
