from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import EvidenceLevel, SusceptibilityLevel


class OliveVariety(Base):
    __tablename__ = "olive_variety"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    susceptibilities: Mapped[list["VarietySusceptibility"]] = relationship(back_populates="variety")


class Threat(Base):
    """Amenaza fitosanitaria o abiótica frente a la que se califica cada variedad."""

    __tablename__ = "threat"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VarietySusceptibility(Base):
    """Relación variedad-amenaza con nivel de susceptibilidad Y nivel de evidencia.

    El campo de evidencia nunca se omite: si no hay una fuente fiable para la
    combinación, o bien no se crea la fila, o bien se crea con
    evidence_level='desconocida' y un nivel neutro ('moderada'), nunca se
    inventa un dato de campo o de laboratorio que no existe.
    """

    __tablename__ = "variety_susceptibility"
    __table_args__ = (UniqueConstraint("variety_id", "threat_id", name="uq_variety_threat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    variety_id: Mapped[int] = mapped_column(ForeignKey("olive_variety.id"), nullable=False)
    threat_id: Mapped[int] = mapped_column(ForeignKey("threat.id"), nullable=False)
    susceptibility_level: Mapped[SusceptibilityLevel] = mapped_column(
        Enum(SusceptibilityLevel, name="susceptibility_level"), nullable=False
    )
    evidence_level: Mapped[EvidenceLevel] = mapped_column(
        Enum(EvidenceLevel, name="evidence_level"), nullable=False
    )
    source_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    variety: Mapped[OliveVariety] = relationship(back_populates="susceptibilities")
    threat: Mapped[Threat] = relationship()
