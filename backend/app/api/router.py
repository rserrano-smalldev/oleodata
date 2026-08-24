from fastapi import APIRouter

from app.api import discovery, health, imports, parcels, varieties

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(discovery.router)
api_router.include_router(parcels.router)
api_router.include_router(varieties.router)
api_router.include_router(imports.router)
