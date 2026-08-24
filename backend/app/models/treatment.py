import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ImportBatchStatus, TreatmentCategory


class Treatment(Base):
    """Cuaderno de campo: un tratamiento aplicado a una parcela.

    `climate_context_frozen` se rellena en el momento de insertar el
    tratamiento con un resumen del clima de los 7 días previos, para poder
    auditar después bajo qué condiciones se decidió la aplicación aunque los
    modelos climáticos se recalculen más adelante.
    """

    __tablename__ = "treatment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcel.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[TreatmentCategory] = mapped_column(
        Enum(TreatmentCategory, name="treatment_category"), nullable=False
    )
    product_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    active_substance: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dose_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    dose_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_pest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    climate_context_frozen: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batch.token"), nullable=True
    )
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcel = relationship("Parcel")


class ImportBatch(Base):
    """Soporta el flujo de importación en dos pasos del módulo 5:
    preview() escribe aquí las filas parseadas (válidas y con error) bajo un
    token; commit(token) es la única operación que escribe en `treatment`.
    """

    __tablename__ = "import_batch"

    token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[ImportBatchStatus] = mapped_column(
        Enum(ImportBatchStatus, name="import_batch_status"),
        nullable=False,
        default=ImportBatchStatus.previewed,
    )
    preview_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
