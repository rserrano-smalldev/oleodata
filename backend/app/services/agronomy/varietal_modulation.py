"""Motor de modulación varietal (módulo 4, punto 5).

Ajusta la presión de riesgo climático (0-1) calculada por un modelo base
(repilo, helada, prays...) según la susceptibilidad de la variedad de la
parcela frente a esa amenaza concreta.

REGLA DE NEGOCIO EXPLÍCITA (no opcional): si la evidencia de la calificación
varietal usada no es de las dos categorías "fuertes" (ensayo_de_campo,
controlado), el sistema NUNCA emite un nivel "crítico" basándose en ese
resultado — se degrada a "alto" y se explica por qué en el texto de la
recomendación.
"""

from dataclasses import dataclass

from app.models.enums import EvidenceLevel, SusceptibilityLevel

SUSCEPTIBILITY_ADJUSTMENT: dict[SusceptibilityLevel, int] = {
    SusceptibilityLevel.altamente_resistente: -2,
    SusceptibilityLevel.resistente: -1,
    SusceptibilityLevel.moderada: 0,
    SusceptibilityLevel.susceptible: 1,
    SusceptibilityLevel.altamente_susceptible: 2,
}

ADJUSTMENT_STEP = 0.15
STRONG_EVIDENCE = {EvidenceLevel.ensayo_de_campo, EvidenceLevel.controlado}

ATTENTION_LEVELS = ("bajo", "moderado", "alto", "critico")


def _level_for_pressure(pressure: float) -> str:
    if pressure < 0.25:
        return "bajo"
    if pressure < 0.5:
        return "moderado"
    if pressure < 0.75:
        return "alto"
    return "critico"


ACTION_BY_LEVEL = {
    "bajo": "vigilar",
    "moderado": "vigilar de cerca en los próximos días",
    "alto": "muestrear en 48h",
    "critico": "consultar al técnico",
}


@dataclass
class ModulatedRisk:
    threat_code: str
    raw_pressure: float
    adjusted_pressure: float
    attention_level: str
    suggested_action: str
    variety_code: str | None
    susceptibility_level: str | None
    evidence_level: str
    evidence_downgrade_applied: bool
    explanation: str


def modulate_risk(
    threat_code: str,
    raw_pressure: float,
    variety_code: str | None,
    susceptibility_level: SusceptibilityLevel | None,
    evidence_level: EvidenceLevel | None,
) -> ModulatedRisk:
    raw_pressure = max(0.0, min(1.0, raw_pressure))

    if susceptibility_level is None:
        adjustment = 0
        effective_evidence = EvidenceLevel.desconocida
        variety_note = (
            "sin calificación varietal fiable para esta combinación variedad-amenaza: "
            "se aplica un ajuste neutro"
        )
    else:
        adjustment = SUSCEPTIBILITY_ADJUSTMENT[susceptibility_level]
        effective_evidence = evidence_level or EvidenceLevel.desconocida
        variety_note = (
            f"variedad calificada como '{susceptibility_level.value}' frente a esta amenaza "
            f"(evidencia: {effective_evidence.value})"
        )

    adjusted = max(0.0, min(1.0, raw_pressure + adjustment * ADJUSTMENT_STEP))
    level = _level_for_pressure(adjusted)

    downgrade_applied = False
    if level == "critico" and effective_evidence not in STRONG_EVIDENCE:
        level = "alto"
        downgrade_applied = True

    explanation_parts = [
        f"presión climática de base {raw_pressure:.2f} sobre 1.0",
        variety_note,
    ]
    if downgrade_applied:
        explanation_parts.append(
            "nivel degradado de 'crítico' a 'alto': la evidencia varietal disponible no "
            "procede de ensayo de campo ni de un ensayo controlado, y el sistema nunca "
            "emite un aviso crítico apoyándose solo en evidencia débil"
        )

    return ModulatedRisk(
        threat_code=threat_code,
        raw_pressure=raw_pressure,
        adjusted_pressure=adjusted,
        attention_level=level,
        suggested_action=ACTION_BY_LEVEL[level],
        variety_code=variety_code,
        susceptibility_level=susceptibility_level.value if susceptibility_level else None,
        evidence_level=effective_evidence.value,
        evidence_downgrade_applied=downgrade_applied,
        explanation="; ".join(explanation_parts),
    )
