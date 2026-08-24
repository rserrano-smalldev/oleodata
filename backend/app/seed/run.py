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


async def _upsert(session: AsyncSession, model, rows: list[dict], conflict_cols: list[str]) -> None:
    """INSERT ... ON CONFLICT DO UPDATE para tablas de catálogo (variable,
    data_provider, olive_variety, threat, variety_susceptibility).

    A diferencia de `observation` (donde DO NOTHING es lo correcto: una
    lectura ya guardada no debe cambiar), estas tablas son código, no datos
    de usuario: si se corrige un valor en el seed (por ejemplo, una
    prioridad de proveedor mal puesta), el arranque siguiente de la API
    debe reflejar el valor corregido, no quedarse con el primero que se
    insertó hace tiempo.
    """
    if not rows:
        return
    stmt = pg_insert(model).values(rows)
    update_cols = {col: getattr(stmt.excluded, col) for col in rows[0].keys() if col not in conflict_cols}
    stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
    await session.execute(stmt)


async def _seed_variables(session: AsyncSession) -> None:
    await _upsert(session, Variable, VARIABLES, ["code"])


async def _seed_providers(session: AsyncSession) -> None:
    await _upsert(session, DataProvider, PROVIDERS, ["code"])


async def _seed_varieties_and_threats(session: AsyncSession) -> None:
    await _upsert(session, OliveVariety, VARIETIES, ["code"])
    await _upsert(session, Threat, THREATS, ["code"])


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

    await _upsert(session, VarietySusceptibility, rows, ["variety_id", "threat_id"])


async def seed_all(engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await _seed_variables(session)
        await _seed_providers(session)
        await _seed_varieties_and_threats(session)
        await session.commit()
        await _seed_susceptibility(session)
        await session.commit()
