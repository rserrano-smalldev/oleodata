"""Modelo derivado y aproximado de humectación foliar, compartido por:

- el simulador de sensores (módulo 3), que lo aplica sobre histórico ERA5-Land
  real para generar la variable `leaf_wetness` guardada como observación
  simulada;
- el motor de recomendaciones (módulo 4), que lo aplica EN MEMORIA (sin
  guardar nada) sobre la previsión de Open-Meteo para estimar el riesgo de
  repilo de los próximos días, donde todavía no existe ninguna lectura de
  sensor (simulado o real).

Ninguna red pública mide humectación foliar directamente: esto es siempre
una aproximación explícita (sube con humedad relativa alta o lluvia, decae
con radiación y viento), nunca una medición real.
"""

from datetime import datetime

WETNESS_RH_THRESHOLD = 90.0
WETNESS_WETTING_RATE = 0.34  # alcanza 1.0 en ~3 horas de condición de mojado
WETNESS_BASE_DRYING_RATE = 0.08
WETNESS_RADIATION_DRYING_FACTOR = 0.15  # a más radiación, más secado
WETNESS_RADIATION_REF_WM2 = 500.0
WETNESS_WIND_DRYING_FACTOR = 0.05
WETNESS_WIND_REF_KMH = 20.0


def compute_hourly_wetness(
    rh_series: dict[datetime, float],
    precip_series: dict[datetime, float],
    radiation_series: dict[datetime, float],
    wind_series: dict[datetime, float],
) -> dict[datetime, float]:
    """Serie horaria de humectación foliar (0-1) a partir de RH, precipitación,
    radiación y viento horarios ya alineados por timestamp."""
    hours = sorted(rh_series.keys())
    wetness: dict[datetime, float] = {}
    state = 0.0
    for hour in hours:
        rh = rh_series.get(hour, 0.0) or 0.0
        precip = precip_series.get(hour, 0.0) or 0.0
        if rh >= WETNESS_RH_THRESHOLD or precip > 0:
            state = min(1.0, state + WETNESS_WETTING_RATE)
        else:
            radiation = radiation_series.get(hour, 0.0) or 0.0
            wind = wind_series.get(hour, 0.0) or 0.0
            drying_rate = (
                WETNESS_BASE_DRYING_RATE
                + WETNESS_RADIATION_DRYING_FACTOR * min(radiation / WETNESS_RADIATION_REF_WM2, 1.0)
                + WETNESS_WIND_DRYING_FACTOR * min(wind / WETNESS_WIND_REF_KMH, 1.0)
            )
            state = max(0.0, state - drying_rate)
        wetness[hour] = state
    return wetness
