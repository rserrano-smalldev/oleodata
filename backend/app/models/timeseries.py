from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import QualityFlag


class Source(Base):
    """Instancia concreta de procedencia de datos: liga un data_provider con,
    según su tipo, una estación física (station_network) o una parcela
    concreta (reanalysis interpolado a esas coordenadas, o sensor simulado de
    esa parcela). Es la fila que sabe si un dato es real o simulado.
    """

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("data_provider.id"), nullable=False)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("station.id"), nullable=True)
    parcel_id: Mapped[int | None] = mapped_column(ForeignKey("parcel.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("DataProvider")
    station = relationship("Station")
    parcel = relationship("Parcel")


class Observation(Base):
    """Tabla ÚNICA de series temporales para todo dato climático, formato largo.

    La procedencia (source_id) es un campo de la fila, no una tabla distinta:
    esto permite comparar fuentes en la misma consulta y añadir una fuente
    nueva sin migrar nada (principio 1 del módulo 1).

    Clave primaria compuesta (timestamp incluido) = hypertable-friendly +
    idempotencia nativa: reinsertar la misma lectura es un no-op.
    """

    __tablename__ = "observation"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), primary_key=True)
    variable_id: Mapped[int] = mapped_column(ForeignKey("variable.id"), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    quality_flag: Mapped[QualityFlag] = mapped_column(
        Enum(QualityFlag, name="quality_flag"), nullable=False, default=QualityFlag.ok
    )
