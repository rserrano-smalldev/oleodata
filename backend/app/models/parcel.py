from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import SensorizationStatus


class Parcel(Base):
    __tablename__ = "parcel"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    variety_id: Mapped[int | None] = mapped_column(ForeignKey("olive_variety.id"), nullable=True)
    area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_capacity_mm: Mapped[float] = mapped_column(
        Float, nullable=False, default=120.0, comment="Capacidad de campo del suelo, mm de agua"
    )
    sensorization_status: Mapped[SensorizationStatus] = mapped_column(
        Enum(SensorizationStatus, name="sensorization_status"),
        nullable=False,
        default=SensorizationStatus.simulada_demo,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    variety = relationship("OliveVariety")
