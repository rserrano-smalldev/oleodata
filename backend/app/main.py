import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.bootstrap import init_db
from app.db import engine

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(engine)
    yield


app = FastAPI(
    title="OleaData — MVP",
    description=(
        "Plataforma de decisión agronómica para olivar. DEMO FUNCIONAL: el histórico "
        "climático de ERA5-Land es real (Open-Meteo, CC BY 4.0); las lecturas de sensor "
        "de parcela son SIMULADAS (no hay hardware instalado todavía, ver /v1/parcels/"
        "{id}/simulate-sensors). El sistema nunca prescribe producto, materia activa ni "
        "dosis: solo indica cuándo muestrear, vigilar o consultar al técnico."
    ),
    version="0.1.0-mvp",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
