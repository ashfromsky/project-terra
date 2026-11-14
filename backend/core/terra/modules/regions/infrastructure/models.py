"""SQLAlchemy ORM model for persisted geographic regions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from terra.infrastructure.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RegionModel(Base):
    """Database table storing user-defined AOI metadata and EPSG:4326 GeoJSON."""

    __tablename__ = "regions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="primary")
    shape_type: Mapped[str] = mapped_column(String(20), nullable=False, default="polygon")
    source_crs: Mapped[str] = mapped_column(String(16), nullable=False, default="EPSG:4326")
    iso_a3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    geometry_geojson: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    approx_area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    centroid: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    vertex_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
