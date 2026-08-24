"""Helpers compartidos para materializar filas de `source` (procedencia)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import DataProvider
from app.models.timeseries import Source


async def get_provider_by_code(session: AsyncSession, code: str) -> DataProvider:
    provider = (
        await session.execute(select(DataProvider).where(DataProvider.code == code))
    ).scalar_one_or_none()
    if provider is None:
        raise ValueError(f"Proveedor de datos desconocido en el catálogo: {code}")
    return provider


async def get_or_create_source(
    session: AsyncSession,
    *,
    provider: DataProvider,
    parcel_id: int,
    code: str,
    is_simulated: bool,
    metadata: dict | None = None,
) -> Source:
    existing = (await session.execute(select(Source).where(Source.code == code))).scalar_one_or_none()
    if existing is not None:
        return existing

    source = Source(
        provider_id=provider.id,
        parcel_id=parcel_id,
        code=code,
        is_simulated=is_simulated,
        metadata_json=metadata or {},
    )
    session.add(source)
    await session.flush()
    return source
