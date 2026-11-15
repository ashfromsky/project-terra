"""SQLAlchemy ORM model for persisted scientific assessments."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from terra.infrastructure.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AssessmentModel(Base):
    """Database table storing scientific assessment requests, status, and deterministic results."""

    __tablename__ = "assessments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    region_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("regions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="queued")
    request_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ghs_dataset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    inline_datasets: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    artifact_paths: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
