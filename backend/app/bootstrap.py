"""Inicialización idempotente de la base de datos.

El MVP no usa un runner de migraciones (Alembic no forma parte del stack
pedido): en su lugar, cada arranque de la API asegura que extensiones, tablas,
la función SQL de distancia efectiva, la hypertable y los catálogos base
existen, usando siempre CREATE ... IF NOT EXISTS / ON CONFLICT DO NOTHING.
Volver a levantar el contenedor, o llamar a este código muchas veces durante
el desarrollo, nunca duplica nada ni falla por "ya existe".
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import Base
from app.models import *  # noqa: F401,F403  (registra las tablas en Base.metadata)
from app.seed.run import seed_all

logger = logging.getLogger(__name__)

EFFECTIVE_DISTANCE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION effective_distance_km(
    horizontal_km double precision,
    elevation_diff_m double precision
) RETURNS double precision AS $$
    -- distancia_efectiva = sqrt(horizontal^2 + (desnivel * 0.1)^2)
    -- El factor 0.1 aproxima el gradiente térmico vertical de ~0.65 C/100m:
    -- 10 km horizontales producen una diferencia térmica del orden de la que
    -- produce un desnivel de 100 m. Ver módulo 2 del README.
    SELECT sqrt(
        power(horizontal_km, 2) + power(coalesce(elevation_diff_m, 0) * 0.1, 2)
    );
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE;
"""


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))

        await conn.run_sync(Base.metadata.create_all)

        # Añadir un valor nuevo a un ENUM de Postgres no lo hace create_all()
        # si el tipo ya existía de una versión anterior del esquema (create_all
        # solo emite CREATE TYPE cuando el tipo no existe todavía). ADD VALUE
        # IF NOT EXISTS es seguro llamarlo siempre: no falla en bases nuevas
        # (donde el tipo ya se creó con este valor incluido) ni en bases
        # existentes que vengan de antes de añadir el proveedor de previsión.
        await conn.execute(text("ALTER TYPE provider_type ADD VALUE IF NOT EXISTS 'forecast'"))

        await conn.execute(text(EFFECTIVE_DISTANCE_FUNCTION_SQL))

        await conn.execute(
            text(
                "SELECT create_hypertable('observation', 'timestamp', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )

    await seed_all(engine)
    logger.info("Base de datos inicializada (extensiones, esquema, función SQL, hypertable, seed).")
