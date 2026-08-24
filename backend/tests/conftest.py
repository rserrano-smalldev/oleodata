import pytest_asyncio

from app.bootstrap import init_db
from app.db import SessionLocal, engine


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _init_database():
    """Se ejecuta una vez por sesión de tests: asegura extensiones, esquema,
    función SQL de distancia efectiva, hypertable y catálogos base. Es
    idempotente (igual que el arranque de la API), así que da igual si ya se
    había ejecutado antes.
    """
    await init_db(engine)
    # El engine async de SQLAlchemy liga su pool de conexiones al event loop
    # en el que se usó por primera vez. pytest-asyncio crea un loop nuevo por
    # test, así que sin este dispose() la siguiente prueba que reutilice el
    # engine (definido a nivel de módulo en app.db) fallaría con
    # "attached to a different loop". Ver también el fixture de más abajo.
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_after_each_test():
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session
