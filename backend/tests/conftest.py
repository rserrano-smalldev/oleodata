import asyncio

import pytest
import pytest_asyncio

from app.bootstrap import init_db
from app.db import SessionLocal, engine


def pytest_collection_modifyitems(config, items):
    """Fuerza que los tests async usen el mismo event loop de sesión que
    _init_database (session-scoped): si los tests corrieran en loops por
    test (el valor por defecto de pytest-asyncio) mientras las fixtures son
    session-scoped, cualquier conexión abierta en una fixture y usada desde
    un test acaba en un RuntimeError "attached to a different loop".
    """
    for item in items:
        test_fn = getattr(item, "function", None)
        if test_fn is not None and asyncio.iscoroutinefunction(test_fn):
            item.add_marker(pytest.mark.asyncio(loop_scope="session"))


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


async def _safe_dispose():
    """engine.dispose() puede toparse con una conexión que otra fixture ya
    está cerrando en paralelo (varios tests comparten un único loop de
    sesión) y lanzar un RuntimeError de "greenlet ya finalizado" o "loop
    distinto" puramente de limpieza del pool, no un fallo de una prueba.
    Se ignora ese ruido en vez de dejar que ensucie el resultado de tests
    cuyas aserciones ya han pasado.
    """
    try:
        await engine.dispose()
    except RuntimeError:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_pool_after_each_test():
    yield
    await _safe_dispose()


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session
        try:
            await session.rollback()
        except RuntimeError:
            pass
