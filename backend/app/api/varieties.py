from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models.variety import OliveVariety, VarietySusceptibility
from app.schemas.variety import SusceptibilityOut, VarietyDetailOut, VarietyOut

router = APIRouter(prefix="/v1/varieties", tags=["varieties"])


@router.get("", response_model=list[VarietyOut])
async def list_varieties(session: AsyncSession = Depends(get_session)):
    varieties = (await session.execute(select(OliveVariety).order_by(OliveVariety.name))).scalars().all()
    return [
        VarietyOut(code=v.code, name=v.name, origin_region=v.origin_region, notes=v.notes) for v in varieties
    ]


@router.get("/{code}", response_model=VarietyDetailOut)
async def get_variety(code: str, session: AsyncSession = Depends(get_session)):
    variety = (
        await session.execute(
            select(OliveVariety)
            .where(OliveVariety.code == code)
            .options(selectinload(OliveVariety.susceptibilities).selectinload(VarietySusceptibility.threat))
        )
    ).scalar_one_or_none()
    if variety is None:
        raise HTTPException(status_code=404, detail="Variedad no encontrada")

    return VarietyDetailOut(
        code=variety.code,
        name=variety.name,
        origin_region=variety.origin_region,
        notes=variety.notes,
        susceptibilities=[
            SusceptibilityOut(
                threat_code=s.threat.code,
                threat_name=s.threat.name,
                susceptibility_level=s.susceptibility_level.value,
                evidence_level=s.evidence_level.value,
                source_reference=s.source_reference,
            )
            for s in variety.susceptibilities
        ],
    )
