"""SQLAlchemy ORM model for Core ingestion tracking records."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from terra.infrastructure.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IngestionOperationModel(Base):
    """Database table linking user AOIs and submitted GHS ingestion jobs."""

    __tablename__ = "ingestion_operations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    region_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("regions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    ghs_job_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dataset_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dataset_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
