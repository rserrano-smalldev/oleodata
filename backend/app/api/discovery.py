from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.discovery import DiscoveryPointRequest, DiscoveryResponse, SourceCandidateOut
from app.services.discovery import discover_sources

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


def candidate_to_out(c) -> SourceCandidateOut:
    return SourceCandidateOut(
        provider_code=c.provider_code,
        provider_name=c.provider_name,
        provider_type=c.provider_type,
        has_adapter=c.has_adapter,
        role=c.role,
        needs_review=c.needs_review,
        review_reason=c.review_reason,
        score=None if c.score in (float("inf"),) else c.score,
        horizontal_km=c.horizontal_km,
        elevation_diff_m=c.elevation_diff_m,
        effective_km=c.effective_km,
        variables_supported=c.variables_supported,
        notes=c.notes,
    )


@router.post("/point", response_model=DiscoveryResponse)
async def discover_point(payload: DiscoveryPointRequest, session: AsyncSession = Depends(get_session)):
    result = await discover_sources(session, payload.lat, payload.lon, payload.elevation)
    return DiscoveryResponse(
        lat=result.lat,
        lon=result.lon,
        elevation_m=result.elevation_m,
        candidates=[candidate_to_out(c) for c in result.candidates],
        coverage_warnings=result.coverage_warnings,
        limitations=result.limitations,
    )
