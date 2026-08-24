from datetime import datetime

from pydantic import BaseModel, Field


class ParcelCreate(BaseModel):
    code: str
    name: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    elevation_m: float | None = Field(
        default=None, description="Si se omite, se resuelve vía la API de elevación de Open-Meteo."
    )
    variety_code: str | None = None
    area_ha: float | None = None
    field_capacity_mm: float = 120.0


class ParcelOut(BaseModel):
    id: int
    code: str
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None
    variety_code: str | None
    area_ha: float | None
    field_capacity_mm: float
    sensorization_status: str
    created_at: datetime
    initial_backfill_note: str | None = None
    ria_note: str | None = None

    model_config = {"from_attributes": True}


class ParcelVarietyUpdate(BaseModel):
    variety_code: str | None = None


class BackfillRequest(BaseModel):
    years_back: int = Field(default=25, ge=1, le=75)


class SimulateSensorsRequest(BaseModel):
    start: datetime | None = Field(
        default=None, description="Si se omite, se usa (fin - 30 días)."
    )
    end: datetime | None = Field(
        default=None, description="Si se omite, se usa el último instante con histórico ERA5-Land disponible."
    )
