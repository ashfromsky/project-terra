"""Domain models for storage zones, quota ledger, deduplication, compression, and lifecycle."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from geospatial_harmonization.domain.exceptions import (
    StorageIntegrityError,
    StorageReservationError,
)
from geospatial_harmonization.domain.models.dataset import DataFormat
from geospatial_harmonization.domain.models.temporal import require_tz_aware

StorageZone = Literal["raw", "intermediate", "derived"]
ObjectStatus = Literal["active", "marked_orphan", "deleting", "deleted"]
ReservationStatus = Literal["active", "committed", "released", "expired", "failed"]
ReferenceKind = Literal["job", "dataset", "result", "manual_hold"]
WarningSeverity = Literal["info", "warning", "critical"]
StorageWarningCode = Literal[
    "BUDGET_WARNING",
    "BUDGET_HARD_LIMIT",
    "JOB_ALLOCATION_HIGH",
    "EXCESSIVE_RESERVATIONS",
    "UNEXPECTED_GROWTH",
    "RECONCILIATION_DRIFT",
    "MISSING_REFERENCED_OBJECT",
    "ORPHANED_OBJECTS_DETECTED",
]
CompressionCodec = Literal["none", "DEFLATE", "ZSTD", "zlib", "zstd", "gzip", "blosc"]


@dataclass(frozen=True, slots=True)
class StoredObjectInfo:
    """Metadata describing an object physically stored in a StoragePort backend."""

    key: str
    size_bytes: int
    last_modified: datetime | None = None
    etag: str | None = None
    media_type: str | None = None
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.key.strip() or self.size_bytes < 0:
            raise StorageIntegrityError("StoredObjectInfo requires non-empty key and size >= 0")
        if self.last_modified is not None:
            require_tz_aware(self.last_modified, "last_modified", StorageIntegrityError)


@dataclass(frozen=True, slots=True)
class StorageObjectRecord:
    """Application-level ledger record tracking stored objects, compression, and refs."""

    object_key: str
    zone: StorageZone
    content_sha256: str
    size_bytes: int
    media_type: str
    data_format: DataFormat
    created_at: datetime
    updated_at: datetime
    original_size_bytes: int | None = None
    compression_codec: str | None = None
    ref_count: int = 0
    status: ObjectStatus = "active"
    marked_orphan_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.object_key.strip() or len(self.content_sha256.strip()) != 64:
            raise StorageIntegrityError(
                "StorageObjectRecord requires non-empty object_key and 64-char SHA-256 checksum"
            )
        if self.size_bytes < 0 or self.ref_count < 0:
            raise StorageIntegrityError("StorageObjectRecord size_bytes and ref_count must be >= 0")
        if self.original_size_bytes is not None and self.original_size_bytes < 0:
            raise StorageIntegrityError("original_size_bytes must be >= 0")
        require_tz_aware(self.created_at, "created_at", StorageIntegrityError)
        require_tz_aware(self.updated_at, "updated_at", StorageIntegrityError)
        if self.marked_orphan_at is not None:
            require_tz_aware(self.marked_orphan_at, "marked_orphan_at", StorageIntegrityError)
        if self.expires_at is not None:
            require_tz_aware(self.expires_at, "expires_at", StorageIntegrityError)


@dataclass(frozen=True, slots=True)
class AssetReferenceLink:
    """Tracks ownership linking a physical storage object to a job, dataset, or result."""

    object_key: str
    ref_kind: ReferenceKind
    ref_owner_id: str
    asset_id: str
    provider: str
    product: str
    created_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("object_key", self.object_key),
            ("ref_owner_id", self.ref_owner_id),
            ("asset_id", self.asset_id),
            ("provider", self.provider),
            ("product", self.product),
        ):
            if not value.strip():
                raise StorageIntegrityError(f"AssetReferenceLink.{label} must be non-empty")
        require_tz_aware(self.created_at, "created_at", StorageIntegrityError)


@dataclass(frozen=True, slots=True)
class StorageReservation:
    """Atomic byte-capacity reservation bound to a job or ingestion operation."""

    reservation_id: UUID
    job_id: str | None
    operation: str
    zone: StorageZone
    reserved_bytes: int
    status: ReservationStatus
    created_at: datetime
    expires_at: datetime
    actual_bytes: int | None = None
    reconciled_at: datetime | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise StorageReservationError("StorageReservation.operation must be non-empty")
        if self.reserved_bytes < 0:
            raise StorageReservationError("reserved_bytes must be >= 0")
        if self.actual_bytes is not None and self.actual_bytes < 0:
            raise StorageReservationError("actual_bytes must be >= 0")
        require_tz_aware(self.created_at, "created_at", StorageReservationError)
        require_tz_aware(self.expires_at, "expires_at", StorageReservationError)
        if self.expires_at <= self.created_at:
            raise StorageReservationError("expires_at must be strictly after created_at")
        if self.reconciled_at is not None:
            require_tz_aware(self.reconciled_at, "reconciled_at", StorageReservationError)


@dataclass(frozen=True, slots=True)
class ZoneRetentionPolicy:
    """Lifecycle and immutability rules governing a logical storage zone."""

    zone: StorageZone
    retention_seconds: int | None
    auto_cleanup_on_job_success: bool
    immutable: bool
    allow_deduplication: bool


@dataclass(frozen=True, slots=True)
class StorageWarning:
    """Structured actionable warning emitted by quota or reconciliation checks."""

    code: StorageWarningCode
    severity: WarningSeverity
    message: str
    action: str
    zone: StorageZone | None = None
    current_bytes: int | None = None
    threshold_bytes: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ZoneUsageSummary:
    """Per-zone consumption and optimization statistics."""

    zone: StorageZone
    object_count: int
    stored_bytes: int
    reserved_bytes: int
    original_bytes: int
    compression_saved_bytes: int
    dedup_saved_bytes: int


@dataclass(frozen=True, slots=True)
class StorageUsageMetricsSnapshot:
    """Ledger-computed totals, savings, growth, and cleanup counters."""

    total_stored_bytes: int
    object_count: int
    reserved_bytes: int
    zones: dict[StorageZone, ZoneUsageSummary]
    daily_growth_bytes: int
    compression_savings_bytes: int
    deduplication_savings_bytes: int
    cleanup_deleted_objects: int
    cleanup_reclaimed_bytes: int
    failed_uploads_count: int
    orphaned_objects_count: int
    missing_referenced_objects_count: int
    last_reconciliation_diff_bytes: int | None
    last_reconciliation_at: datetime | None


@dataclass(frozen=True, slots=True)
class StorageUsageSummary:
    """Unified storage monitoring snapshot across all zones and quota thresholds."""

    budget_bytes: int
    warning_threshold: float
    hard_limit_threshold: float
    hard_limit_bytes: int
    total_stored_bytes: int
    object_count: int
    reserved_bytes: int
    available_budget_bytes: int
    utilization_ratio: float
    zones: dict[StorageZone, ZoneUsageSummary]
    daily_growth_bytes: int
    compression_savings_bytes: int
    deduplication_savings_bytes: int
    cleanup_deleted_objects: int
    cleanup_reclaimed_bytes: int
    failed_uploads_count: int
    orphaned_objects_count: int
    missing_referenced_objects_count: int
    reconciliation_diff_bytes: int | None
    warnings: tuple[StorageWarning, ...]
    measured_at: datetime


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Result of reconciling the database ledger with physical object storage."""

    ledger_bytes: int
    actual_store_bytes: int
    bytes_difference: int
    ledger_object_count: int
    actual_store_object_count: int
    untracked_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    expired_reservations_reconciled: int
    warnings: tuple[StorageWarning, ...]
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class PrecisionPolicy:
    """Scientific precision preservation rules forbidding silent precision loss."""

    preserve_float64: bool = True
    preserve_integer_dtype: bool = True
    allow_lossy_compression: bool = False
    allow_quantization: bool = False


@dataclass(frozen=True, slots=True)
class CompressionPolicy:
    """Configurable lossless compression policy per format."""

    enabled: bool = True
    raster_codec: Literal["DEFLATE", "ZSTD"] = "ZSTD"
    raster_cog_enabled: bool = True
    raster_block_size: int = 512
    netcdf_complevel: int = 4
    zarr_codec: Literal["zstd", "gzip", "blosc"] = "zstd"
    zarr_target_chunk_bytes: int = 1_048_576
    min_recompress_savings_ratio: float = 0.05
    precision: PrecisionPolicy = field(default_factory=PrecisionPolicy)

    def __post_init__(self) -> None:
        if self.raster_block_size < 16 or self.raster_block_size % 16 != 0:
            raise StorageIntegrityError("raster_block_size must be a positive multiple of 16")
        if not 1 <= self.netcdf_complevel <= 9:
            raise StorageIntegrityError("netcdf_complevel must lie in [1, 9]")
        if not 0.0 <= self.min_recompress_savings_ratio < 1.0:
            raise StorageIntegrityError("min_recompress_savings_ratio must lie in [0, 1)")


@dataclass(frozen=True, slots=True)
class CompressionResult:
    """Outcome of a lossless compression pass including preserved provenance metadata."""

    output_path: str
    data_format: DataFormat
    codec: str
    original_bytes: int
    compressed_bytes: int
    saved_bytes: int
    skipped_reason: str | None = None
    metadata_preserved: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    """Candidate storage object or artifact evaluated by mark-and-sweep cleanup."""

    object_key: str
    zone: StorageZone
    size_bytes: int
    reason: str
    marked_orphan_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OrphanReport:
    """Orphan and missing-reference integrity audit result."""

    untracked_in_store: tuple[str, ...]
    unreferenced_in_ledger: tuple[str, ...]
    missing_from_store: tuple[str, ...]
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Auditable outcome of a lifecycle cleanup / mark-and-sweep execution."""

    dry_run: bool
    expired_intermediate_deleted: tuple[str, ...]
    failed_job_artifacts_deleted: tuple[str, ...]
    orphans_marked: tuple[str, ...]
    orphans_swept: tuple[str, ...]
    missing_detected: tuple[str, ...]
    abandoned_temp_files_removed: int
    abandoned_multipart_aborted: int
    reclaimed_bytes: int
    skipped_protected: tuple[str, ...]
    executed_at: datetime
