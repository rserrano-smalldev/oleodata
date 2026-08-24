"""Regresión: la previsión (open_meteo_forecast) nunca debe tener mejor
prioridad que el histórico real (era5_land) en el catálogo de proveedores.
Si la tuviera, la vista combinada de /daily (services/daily_series.py)
dejaría que una previsión sobrescribiera un dato histórico ya confirmado en
cualquier día de solape."""

from sqlalchemy import select

from app.models.catalog import DataProvider


async def test_forecast_provider_has_worse_priority_than_era5_land(db_session):
    era5 = (
        await db_session.execute(select(DataProvider).where(DataProvider.code == "era5_land"))
    ).scalar_one()
    forecast = (
        await db_session.execute(select(DataProvider).where(DataProvider.code == "open_meteo_forecast"))
    ).scalar_one()

    assert forecast.base_priority > era5.base_priority


async def test_simulated_sensor_has_better_priority_than_era5_land(db_session):
    """El simulador representa un futuro sensor propio en la parcela, que en
    la realidad sería más fiable localmente que una rejilla de ~9 km: debe
    ganar sobre ERA5-Land quando ambos cubren la misma variable/día."""
    era5 = (
        await db_session.execute(select(DataProvider).where(DataProvider.code == "era5_land"))
    ).scalar_one()
    sim = (
        await db_session.execute(select(DataProvider).where(DataProvider.code == "sim_sensor_v1"))
    ).scalar_one()

    assert sim.base_priority < era5.base_priority
