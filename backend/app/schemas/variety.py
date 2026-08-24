from pydantic import BaseModel


class SusceptibilityOut(BaseModel):
    threat_code: str
    threat_name: str
    susceptibility_level: str
    evidence_level: str
    source_reference: str | None


class VarietyOut(BaseModel):
    code: str
    name: str
    origin_region: str | None
    notes: str | None


class VarietyDetailOut(VarietyOut):
    susceptibilities: list[SusceptibilityOut]
