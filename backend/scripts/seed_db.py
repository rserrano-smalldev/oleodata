"""Vuelve a ejecutar el seed de catálogos de forma idempotente.

Útil tras un `make reset-db`, o simplemente para confirmar que los catálogos
están al día sin tener que reiniciar el contenedor de la API (que ya
ejecuta esto mismo en su arranque, ver app/bootstrap.py).
"""

import asyncio

from app.db import engine
from app.seed.run import seed_all


async def main():
    await seed_all(engine)
    print("Seed de catálogos completado (idempotente).")


if __name__ == "__main__":
    asyncio.run(main())
