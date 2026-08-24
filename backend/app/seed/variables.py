"""Catálogo de variables. Añadir una variable nueva = añadir un dict aquí,
nunca tocar el esquema de la tabla observation.
"""

VARIABLES = [
    {
        "code": "temperature_2m",
        "name": "Temperatura del aire a 2 m",
        "unit": "°C",
        "aggregation_type": "mean",
        "valid_min": -30.0,
        "valid_max": 55.0,
        "description": "Temperatura instantánea del aire a 2 metros de altura.",
    },
    {
        "code": "relative_humidity_2m",
        "name": "Humedad relativa a 2 m",
        "unit": "%",
        "aggregation_type": "mean",
        "valid_min": 0.0,
        "valid_max": 100.0,
        "description": "Humedad relativa instantánea del aire a 2 metros de altura.",
    },
    {
        "code": "precipitation",
        "name": "Precipitación",
        "unit": "mm",
        "aggregation_type": "sum",
        "valid_min": 0.0,
        "valid_max": 100.0,
        "description": "Precipitación acumulada en el intervalo de la lectura.",
    },
    {
        "code": "wind_speed_10m",
        "name": "Velocidad del viento a 10 m",
        "unit": "km/h",
        "aggregation_type": "mean",
        "valid_min": 0.0,
        "valid_max": 200.0,
        "description": "Velocidad instantánea del viento a 10 metros de altura.",
    },
    {
        "code": "shortwave_radiation",
        "name": "Radiación solar de onda corta",
        "unit": "W/m²",
        "aggregation_type": "mean",
        "valid_min": 0.0,
        "valid_max": 1400.0,
        "description": "Irradiancia solar instantánea.",
    },
    {
        "code": "soil_moisture_7_28cm",
        "name": "Humedad del suelo (7-28 cm)",
        "unit": "%",
        "aggregation_type": "mean",
        "valid_min": 0.0,
        "valid_max": 60.0,
        "description": (
            "Contenido volumétrico de agua en la capa 7-28 cm, convertido de "
            "fracción m³/m³ a porcentaje."
        ),
    },
    {
        "code": "et0_fao_evapotranspiration",
        "name": "Evapotranspiración de referencia FAO-56 (ET0)",
        "unit": "mm",
        "aggregation_type": "sum",
        "valid_min": 0.0,
        "valid_max": 15.0,
        "description": "Evapotranspiración de referencia diaria, método FAO Penman-Monteith.",
    },
    {
        "code": "leaf_wetness",
        "name": "Humectación foliar",
        "unit": "fraccion_0_1",
        "aggregation_type": "mean",
        "valid_min": 0.0,
        "valid_max": 1.0,
        "description": (
            "Fracción del intervalo con hoja mojada (1=mojada, 0=seca). Ninguna red "
            "pública mide esta variable: en este MVP es siempre un dato 100% "
            "simulado (ver módulo 3), derivado de humedad relativa/radiación/viento "
            "de ERA5-Land como proxy de rocío/niebla."
        ),
    },
]
