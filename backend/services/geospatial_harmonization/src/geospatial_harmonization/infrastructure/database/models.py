"""SQLAlchemy ORM models for GHS datasets, assets, and durable async jobs."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
        Index("ix_ghs_jobs_status_next_retry_at", "status", "next_retry_at"),
        Index("ix_ghs_jobs_idempotency_key", "idempotency_key"),
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
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GhsStorageLedgerStateModel(GhsBase):
    """Singleton storage quota ledger row locked during capacity reservations and accounting."""

    __tablename__ = "ghs_storage_ledger_state"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    total_stored_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    intermediate_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    derived_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    compression_savings_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    deduplication_savings_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cleanup_deleted_objects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleanup_reclaimed_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_uploads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orphaned_objects_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_referenced_objects_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_reconciliation_diff_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GhsStorageObjectModel(GhsBase):
    """Application storage ledger record tracking zone placement, checksums, and lifecycle."""

    __tablename__ = "ghs_storage_objects"
    __table_args__ = (
        Index("ix_ghs_storage_objects_zone_status", "zone", "status"),
        Index("ix_ghs_storage_objects_sha_status", "content_sha256", "status"),
        Index("ix_ghs_storage_objects_zone_expires", "zone", "status", "expires_at"),
    )

    object_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    zone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data_format: Mapped[str] = mapped_column(String(32), nullable=False)
    compression_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    marked_orphan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    refs: Mapped[list["GhsStorageAssetRefModel"]] = relationship(
        back_populates="storage_object",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GhsStorageAssetRefModel(GhsBase):
    """Ownership links connecting physical storage objects to jobs, datasets, and results."""

    __tablename__ = "ghs_storage_asset_refs"
    __table_args__ = (
        UniqueConstraint(
            "object_key",
            "ref_kind",
            "ref_owner_id",
            "asset_id",
            name="uq_ghs_storage_asset_ref",
        ),
        Index("ix_ghs_storage_asset_refs_owner", "ref_kind", "ref_owner_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_key: Mapped[str] = mapped_column(
        String(512),
        ForeignKey("ghs_storage_objects.object_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(512), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(_JSON_VARIANT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    storage_object: Mapped[GhsStorageObjectModel] = relationship(back_populates="refs")


class GhsStorageReservationModel(GhsBase):
    """Pre-write storage budget reservations supporting atomic reconciliation and expiration."""

    __tablename__ = "ghs_storage_reservations"
    __table_args__ = (Index("ix_ghs_storage_reservations_status_expires", "status", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    zone: Mapped[str] = mapped_column(String(32), nullable=False)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GhsStorageAuditEventModel(GhsBase):
    """Auditable ledger events covering allocations, deduplication, deletions, and drift."""

    __tablename__ = "ghs_storage_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    zone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bytes_delta: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    saved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    details_json: Mapped[dict[str, object]] = mapped_column(_JSON_VARIANT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
