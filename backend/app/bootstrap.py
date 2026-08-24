"""Inicialización idempotente de la base de datos.

El MVP no usa un runner de migraciones (Alembic no forma parte del stack
pedido): en su lugar, cada arranque de la API asegura que extensiones, tablas,
la función SQL de distancia efectiva, la hypertable y los catálogos base
existen, usando siempre CREATE ... IF NOT EXISTS / ON CONFLICT DO NOTHING.
Volver a levantar el contenedor, o llamar a este código muchas veces durante
el desarrollo, nunca duplica nada ni falla por "ya existe".
"""

import logging

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import Base, SessionLocal
from app.models import *  # noqa: F401,F403  (registra las tablas en Base.metadata)
from app.seed.run import seed_all
from app.services.ria_client import RIAAdapter
from app.services.ria_sync import ensure_ria_stations_cached

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

        # Igual que con el ENUM anterior: create_all() no altera una tabla
        # `station` que ya existía de una versión anterior del esquema (antes
        # de que RIA necesitara un UNIQUE (provider_id, code) para poder
        # cachear su listado de estaciones de forma idempotente). El bloque
        # DO comprueba pg_constraint antes de añadirla, así que es seguro
        # ejecutarlo en cada arranque tanto en bases nuevas como existentes.
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_station_provider_code'
                    ) THEN
                        ALTER TABLE station
                            ADD CONSTRAINT uq_station_provider_code UNIQUE (provider_id, code);
                    END IF;
                END $$;
                """
            )
        )

        await conn.execute(text(EFFECTIVE_DISTANCE_FUNCTION_SQL))

        await conn.execute(
            text(
                "SELECT create_hypertable('observation', 'timestamp', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )

    await seed_all(engine)

    # Caché EAGER del listado real de estaciones RIA: se hace aquí, en el
    # arranque de la API, para que la tabla `station` ya esté poblada "desde
    # el principio" y no dependa de que alguien dé de alta o sincronice una
    # parcela primero (pedido explícito del usuario, tras comprobar que la
    # caché perezosa nunca llegaba a dispararse a tiempo). ensure_ria_stations_cached
    # ya es idempotente — no vuelve a llamar a la red si ya hay estaciones
    # cacheadas —, así que en arranques posteriores esto es solo una consulta
    # COUNT(*). Nunca bloquea el arranque de la API si RIA no responde
    # (docker sin salida a internet, mantenimiento de la Junta de Andalucía,
    # timeout corto para no alargar el arranque): se degrada a un aviso en
    # el log, igual que el resto de llamadas a APIs externas de este MVP; se
    # reintentará automáticamente al dar de alta o sincronizar una parcela.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            async with SessionLocal() as session:
                station_count = await ensure_ria_stations_cached(session, adapter=RIAAdapter(client=client))
        logger.info("RIA: %d estaciones reales cacheadas (o ya existentes) en el arranque.", station_count)
    except httpx.HTTPError as exc:
        logger.warning(
            "RIA: no se pudo cachear el listado de estaciones en el arranque (%s). "
            "Se reintentará al dar de alta o sincronizar una parcela.",
            exc,
        )

    logger.info("Base de datos inicializada (extensiones, esquema, función SQL, hypertable, seed).")
