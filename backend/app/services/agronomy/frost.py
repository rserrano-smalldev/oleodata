"""Riesgo de helada por fase fenológica.

El umbral de daño no es fijo: depende de si el olivo está en reposo
invernal (aguanta hasta -7/-12 °C) o en floración (daño ya desde -1/-3 °C).
La fase fenológica se aproxima por mes del año (calendario del hemisferio
norte, clima mediterráneo) porque este MVP no observa fenología real de
campo — es un valor de partida, no una observación.

AVISO: los umbrales y los meses de cada fase son aproximaciones de
literatura agronómica general y deben calibrarse con observaciones reales
de la parcela (variedad, altitud, microclima) antes de un uso productivo.
"""

from dataclasses import dataclass


@dataclass
class PhenoPhase:
    phase: str
    damage_threshold_c: float
    severe_threshold_c: float


# month (1-12) -> fase aproximada. Válido para clima mediterráneo del
# hemisferio norte; no aplicable sin adaptar al hemisferio sur.
_PHENOPHASE_BY_MONTH: dict[int, PhenoPhase] = {
    12: PhenoPhase("reposo_invernal", -7.0, -12.0),
    1: PhenoPhase("reposo_invernal", -7.0, -12.0),
    2: PhenoPhase("reposo_invernal", -7.0, -12.0),
    3: PhenoPhase("brotacion", -4.0, -7.0),
    4: PhenoPhase("floracion", -1.0, -3.0),
    5: PhenoPhase("floracion", -1.0, -3.0),
    6: PhenoPhase("cuajado_desarrollo_fruto", -2.0, -5.0),
    7: PhenoPhase("desarrollo_fruto", -2.0, -5.0),
    8: PhenoPhase("desarrollo_fruto", -2.0, -5.0),
    9: PhenoPhase("envero", -2.0, -5.0),
    10: PhenoPhase("maduracion", -2.0, -5.0),
    11: PhenoPhase("post_recoleccion_reposo", -4.0, -7.0),
}


def phenophase_for_month(month: int) -> PhenoPhase:
    return _PHENOPHASE_BY_MONTH[month]


@dataclass
class FrostAssessment:
    phase: str
    daily_min_temp_c: float
    damage_threshold_c: float
    severe_threshold_c: float
    risk_level: str  # ninguno | dano_posible | dano_severo


def assess_frost_risk(daily_min_temp_c: float, month: int) -> FrostAssessment:
    phase = phenophase_for_month(month)
    if daily_min_temp_c <= phase.severe_threshold_c:
        level = "dano_severo"
    elif daily_min_temp_c <= phase.damage_threshold_c:
        level = "dano_posible"
    else:
        level = "ninguno"
    return FrostAssessment(
        phase=phase.phase,
        daily_min_temp_c=daily_min_temp_c,
        damage_threshold_c=phase.damage_threshold_c,
        severe_threshold_c=phase.severe_threshold_c,
        risk_level=level,
    )
