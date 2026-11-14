"""SQLAlchemy ORM models for GHS datasets, assets, and durable async jobs."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from geospatial_harmonization.infrastructure.database.base import GhsBase

_JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class GhsDatasetModel(GhsBase):
    """Persisted metadata envelope for a canonical SpatialDataset."""

    __tablename__ = "ghs_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_json: Mapped[dict[str, object]] = mapped_column(_JSON_VARIANT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    assets: Mapped[list["GhsAssetModel"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GhsAssetModel(GhsBase):
    """Normalized asset inventory linked to a persisted SpatialDataset."""

    __tablename__ = "ghs_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ghs_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[str] = mapped_column(String(512), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    data_format: Mapped[str] = mapped_column(String(32), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dataset: Mapped[GhsDatasetModel] = relationship(back_populates="assets")


class GhsHarmonizationJobModel(GhsBase):
    """Durable async harmonization job claimed via PostgreSQL FOR UPDATE SKIP LOCKED."""

    __tablename__ = "ghs_harmonization_jobs"
    __table_args__ = (
        Index("ix_ghs_jobs_status_created_at", "status", "created_at"),
        Index("ix_ghs_jobs_status_lease_expires_at", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_json: Mapped[dict[str, object]] = mapped_column(_JSON_VARIANT, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
