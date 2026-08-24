from datetime import date

from pydantic import BaseModel


class ThreatRecommendationOut(BaseModel):
    threat_code: str
    attention_level: str
    suggested_action: str
    explanation: str
    evidence_level: str
    evidence_downgrade_applied: bool
    model_detail: dict


class WaterBalanceOut(BaseModel):
    status: str
    suggested_action: str
    reservoir_mm: float
    field_capacity_mm: float
    deficit_mm: float
    lookback_days: int
    note: str


class RecommendationsOut(BaseModel):
    day: date
    variety_code: str | None
    threats: list[ThreatRecommendationOut]
    water_balance: WaterBalanceOut | None
    not_dynamically_modeled_threats: list[str]
    disclaimer: str
    warnings: list[str]
