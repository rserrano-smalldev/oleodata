"""Riesgo de repilo (Fusicladium oleagineum / Venturia oleaginea).

Detecta periodos continuos de humectación foliar (dato SIMULADO del módulo 3
— ninguna red pública lo mide) y calcula si las horas de humectación
superan las horas necesarias para la infección según la temperatura media
del periodo mojado. La relación horas-necesarias vs temperatura sigue una
curva en U (mínimo de horas necesarias en el óptimo ~15-20 °C, más horas
necesarias cuanto más se aleja la temperatura de ese óptimo), y fuera de un
rango viable de temperatura se considera que la infección no es posible por
mucha humectación que haya.

AVISO: los parámetros (horas mínimas, pendiente de la curva, rango viable)
son valores de partida de literatura agronómica general sobre este tipo de
modelos (curvas de infección tipo Mills para hongos foliares), NO
calibrados con ensayos de campo de esta explotación. Requieren calibración
antes de un uso productivo. Se refleja también en las respuestas de la API.
"""

from dataclasses import dataclass

REPILO_OPTIMAL_TEMP_C = 17.5  # punto medio del óptimo 15-20 °C
REPILO_MIN_REQUIRED_HOURS = 12.0  # horas necesarias en el óptimo
REPILO_CURVE_STEEPNESS = 0.5  # horas extra por °C^2 de distancia al óptimo
REPILO_VIABLE_MIN_TEMP_C = 5.0
REPILO_VIABLE_MAX_TEMP_C = 28.0


@dataclass
class RepiloAssessment:
    continuous_wetness_hours: float
    mean_temp_during_wetness: float
    required_hours: float
    infection_triggered: bool
    pressure_ratio: float  # continuous_wetness_hours / required_hours, capado a un máximo razonable


def required_wetness_hours(mean_temp_c: float) -> float:
    """Horas de humectación continua necesarias para que haya infección a
    esta temperatura media. float('inf') fuera del rango viable: no hay
    infección posible por mucha humectación que se acumule.
    """
    if mean_temp_c < REPILO_VIABLE_MIN_TEMP_C or mean_temp_c > REPILO_VIABLE_MAX_TEMP_C:
        return float("inf")
    distance = mean_temp_c - REPILO_OPTIMAL_TEMP_C
    return REPILO_MIN_REQUIRED_HOURS + REPILO_CURVE_STEEPNESS * (distance ** 2)


def assess_repilo_risk(continuous_wetness_hours: float, mean_temp_during_wetness: float) -> RepiloAssessment:
    required = required_wetness_hours(mean_temp_during_wetness)
    triggered = continuous_wetness_hours >= required if required != float("inf") else False
    ratio = 0.0 if required == float("inf") else min(continuous_wetness_hours / required, 3.0)
    return RepiloAssessment(
        continuous_wetness_hours=continuous_wetness_hours,
        mean_temp_during_wetness=mean_temp_during_wetness,
        required_hours=required,
        infection_triggered=triggered,
        pressure_ratio=ratio,
    )


def find_longest_wet_spell(
    samples: list[tuple[float, float, float]], wet_threshold: float = 0.5
) -> tuple[float, float]:
    """Dada una serie ordenada de muestras (paso_horas, wetness_fraction_0_1,
    temperatura), agrupa las rachas contiguas con wetness >= wet_threshold y
    devuelve (horas_continuas_de_la_racha_mas_larga, temperatura_media_de_esa_racha).

    Cada tupla es (intervalo_horas_de_esta_muestra, wetness, temperatura); el
    intervalo permite usar series a cualquier resolución (15 min, horaria...).
    """
    best_hours = 0.0
    best_mean_temp = 0.0

    current_hours = 0.0
    current_temp_sum = 0.0

    for step_hours, wetness, temperature in samples:
        if wetness >= wet_threshold:
            current_hours += step_hours
            current_temp_sum += temperature * step_hours
        else:
            if current_hours > best_hours:
                best_hours = current_hours
                best_mean_temp = current_temp_sum / current_hours if current_hours else 0.0
            current_hours = 0.0
            current_temp_sum = 0.0

    if current_hours > best_hours:
        best_hours = current_hours
        best_mean_temp = current_temp_sum / current_hours if current_hours else 0.0

    return best_hours, best_mean_temp
