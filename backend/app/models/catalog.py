from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import AggregationType, ProviderType


class Variable(Base):
    """Catálogo desnormalizado de variables climáticas/agronómicas.

    Añadir una variable nueva es un INSERT en esta tabla, nunca un ALTER TABLE
    de la tabla de observaciones (principio 2 del módulo 1).
    """

    __tablename__ = "variable"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregation_type: Mapped[AggregationType] = mapped_column(
        Enum(AggregationType, name="aggregation_type"), nullable=False
    )
    valid_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class DataProvider(Base):
    """Catálogo de proveedores de datos climáticos.

    `coverage_geom` NULL significa cobertura global (caso de un reanálisis).
    `adapter_name` referencia la clase Python que sabe hablar con este
    proveedor; `has_adapter=False` dice que el proveedor está catalogado pero
    sin integración todavía (ej. AEMET, SIAR, RIA en este MVP): la arquitectura
    queda lista para añadirlo sin migrar el esquema.
    """

    __tablename__ = "data_provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[ProviderType] = mapped_column(Enum(ProviderType, name="provider_type"), nullable=False)
    coverage_geom = mapped_column(Geography(geometry_type="GEOMETRY", srid=4326), nullable=True)
    base_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Menor valor = mejor prioridad base"
    )
    adapter_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    has_adapter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    variables_supported: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    stations: Mapped[list["Station"]] = relationship(back_populates="provider")


class Station(Base):
    """Estación física perteneciente a un proveedor de tipo station_network.

    En este MVP no hay ningún proveedor de red de estaciones con adaptador
    implementado, así que esta tabla existe pero puede estar vacía: queda
    lista para cuando se añadan AEMET/SIAR/RIA.
    """

    __tablename__ = "station"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("data_provider.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider: Mapped[DataProvider] = relationship(back_populates="stations")
