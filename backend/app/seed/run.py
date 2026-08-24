import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.catalog import DataProvider, Variable
from app.models.variety import OliveVariety, Threat, VarietySusceptibility
from app.seed.providers import PROVIDERS
from app.seed.variables import VARIABLES
from app.seed.varieties import THREATS, VARIETIES, VARIETY_SUSCEPTIBILITY

logger = logging.getLogger(__name__)


async def _seed_variables(session: AsyncSession) -> None:
    stmt = pg_insert(Variable).values(VARIABLES).on_conflict_do_nothing(index_elements=["code"])
    await session.execute(stmt)


async def _seed_providers(session: AsyncSession) -> None:
    stmt = pg_insert(DataProvider).values(PROVIDERS).on_conflict_do_nothing(index_elements=["code"])
    await session.execute(stmt)


async def _seed_varieties_and_threats(session: AsyncSession) -> None:
    stmt = pg_insert(OliveVariety).values(VARIETIES).on_conflict_do_nothing(index_elements=["code"])
    await session.execute(stmt)
    stmt = pg_insert(Threat).values(THREATS).on_conflict_do_nothing(index_elements=["code"])
    await session.execute(stmt)


async def _seed_susceptibility(session: AsyncSession) -> None:
    variety_ids = dict((await session.execute(select(OliveVariety.code, OliveVariety.id))).all())
    threat_ids = dict((await session.execute(select(Threat.code, Threat.id))).all())

    rows = []
    for variety_code, threat_code, level, evidence, reference in VARIETY_SUSCEPTIBILITY:
        variety_id = variety_ids.get(variety_code)
        threat_id = threat_ids.get(threat_code)
        if variety_id is None or threat_id is None:
            logger.warning("Seed: variedad/amenaza desconocida %s/%s, se omite", variety_code, threat_code)
            continue
        rows.append(
            {
                "variety_id": variety_id,
                "threat_id": threat_id,
                "susceptibility_level": level,
                "evidence_level": evidence,
                "source_reference": reference,
            }
        )

    if rows:
        stmt = (
            pg_insert(VarietySusceptibility)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["variety_id", "threat_id"])
        )
        await session.execute(stmt)


async def seed_all(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await _seed_variables(session)
        await _seed_providers(session)
        await _seed_varieties_and_threats(session)
        await session.commit()
        await _seed_susceptibility(session)
        await session.commit()
