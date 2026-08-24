from pydantic import BaseModel, Field


class DiscoveryPointRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    elevation: float | None = Field(
        default=None, description="Altitud en metros; si se omite se usa 0 solo para el cálculo de desnivel."
    )


class SourceCandidateOut(BaseModel):
    provider_code: str
    provider_name: str
    provider_type: str
    has_adapter: bool
    role: str | None
    needs_review: bool
    review_reason: str | None
    score: float | None
    horizontal_km: float | None
    elevation_diff_m: float | None
    effective_km: float | None
    variables_supported: list[str]
    notes: str | None


class DiscoveryResponse(BaseModel):
    lat: float
    lon: float
    elevation_m: float | None
    candidates: list[SourceCandidateOut]
    coverage_warnings: list[str]
    limitations: list[str]
