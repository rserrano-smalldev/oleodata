"""Regresión: los catálogos de seed (variable, data_provider, olive_variety,
threat, variety_susceptibility) son código, no datos de usuario. Si se
corrige un valor en el seed, el siguiente arranque de la API debe
propagarlo, no quedarse con lo que ya hubiera en la base (a diferencia de
`observation`, donde SÍ es correcto no tocar una lectura ya guardada)."""

from sqlalchemy import select, update

from app.db import engine
from app.models.catalog import DataProvider
from app.seed.providers import PROVIDERS
from app.seed.run import seed_all


async def test_reseeding_repairs_a_manually_corrupted_catalog_value(db_session):
    era5_code = "era5_land"
    correct_priority = next(p["base_priority"] for p in PROVIDERS if p["code"] == era5_code)

    await db_session.execute(
        update(DataProvider).where(DataProvider.code == era5_code).values(base_priority=9999)
    )
    await db_session.commit()

    corrupted = (
        await db_session.execute(select(DataProvider.base_priority).where(DataProvider.code == era5_code))
    ).scalar_one()
    assert corrupted == 9999

    await seed_all(engine)

    repaired = (
        await db_session.execute(select(DataProvider.base_priority).where(DataProvider.code == era5_code))
    ).scalar_one()
    assert repaired == correct_priority
