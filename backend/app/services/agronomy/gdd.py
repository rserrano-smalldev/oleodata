"""Grados-día de desarrollo (GDD) por el método del seno simple truncado
(Baskerville & Emin, 1969), usado aquí para trackear el desarrollo de Prays
oleae (polilla del olivo), umbral base ~12.5 °C.

AVISO: el umbral base es un valor de partida de literatura general. Requiere
calibración con datos de campo reales antes de un uso productivo (ver
módulo 4 del README). Esto se refleja también en el texto de las respuestas
de la API que usan este modelo.
"""

import math

PRAYS_OLEAE_BASE_TEMP_C = 12.5


def single_sine_gdd(t_min: float, t_max: float, t_base: float) -> float:
    """Grados-día de un día, método del seno simple truncado (sin umbral superior).

    Más preciso que la media aritmética (t_max+t_min)/2 - t_base cuando la
    temperatura mínima del día cae por debajo del umbral base: en ese caso
    solo la parte del ciclo senoidal diario que queda por encima del umbral
    "cuenta", y se integra analíticamente en vez de promediar todo el día.
    """
    if t_max <= t_base:
        return 0.0
    if t_min >= t_base:
        return (t_max + t_min) / 2.0 - t_base

    mean = (t_max + t_min) / 2.0
    amplitude = (t_max - t_min) / 2.0
    theta = math.asin((t_base - mean) / amplitude)
    gdd = (1.0 / math.pi) * (
        (mean - t_base) * (math.pi / 2.0 - theta) + amplitude * math.cos(theta)
    )
    return max(0.0, gdd)


def prays_oleae_daily_gdd(t_min: float, t_max: float) -> float:
    return single_sine_gdd(t_min, t_max, PRAYS_OLEAE_BASE_TEMP_C)


def accumulate_gdd(daily_min_max: list[tuple[float, float]], t_base: float = PRAYS_OLEAE_BASE_TEMP_C) -> float:
    """Suma de GDD sobre una lista de tuplas (t_min, t_max) diarias."""
    return sum(single_sine_gdd(t_min, t_max, t_base) for t_min, t_max in daily_min_max)
