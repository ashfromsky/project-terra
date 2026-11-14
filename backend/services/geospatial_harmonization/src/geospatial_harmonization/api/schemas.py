"""Pydantic request and response schemas for the Geospatial Harmonization REST API."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.domain.models.grid import (
    AffineMatrix,
    GridAlignmentPolicy,
    GridSpec,
    PixelConvention,
    ResolutionUnit,
    SpatialBounds,
)
from geospatial_harmonization.domain.models.harmonization import (
    HarmonizationJob,
    HarmonizationPlan,
    JobStatus,
    OutputFormat,
    ProcessingResult,
    QualityReport,
    ResamplingMethod,
    ResamplingPolicy,
)
from geospatial_harmonization.domain.models.storage import (
    CleanupReport,
    ReconciliationReport,
    StorageUsageSummary,
    StorageZone,
)
from geospatial_harmonization.domain.models.temporal import (
    TemporalAggregationKind,
    TemporalSemantics,
    TemporalSpec,
)


class DependencyHealth(BaseModel):
    status: Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    service: str
    version: str
    checks: dict[str, DependencyHealth]


class BoundsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def to_domain(self) -> SpatialBounds:
        return SpatialBounds(self.min_x, self.min_y, self.max_x, self.max_y)


class GridSpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crs: str
    resolution_x: float
    resolution_y: float
    resolution_unit: ResolutionUnit = "meter"
    bounds: BoundsIn
    width: int | None = None
    height: int | None = None
    transform: tuple[float, float, float, float, float, float] | None = None
    alignment_policy: GridAlignmentPolicy = "bounds_origin"
    pixel_convention: PixelConvention = "corner"

    def to_domain(self) -> GridSpec:
        affine = AffineMatrix(*self.transform) if self.transform is not None else None
        return GridSpec(
            crs=self.crs,
            resolution_x=self.resolution_x,
            resolution_y=self.resolution_y,
            resolution_unit=self.resolution_unit,
            bounds=self.bounds.to_domain(),
            width=self.width,
            height=self.height,
            transform=affine,
            alignment_policy=self.alignment_policy,
            pixel_convention=self.pixel_convention,
        )


class TemporalSpecIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    cadence: str = "irregular"
    semantics: TemporalSemantics = "interval"
    aggregation: TemporalAggregationKind = "none"
    composite_days: int | None = None

    def to_domain(self) -> TemporalSpec:
        return TemporalSpec(
            start=self.start,
            end=self.end,
            cadence=self.cadence,
            semantics=self.semantics,
            aggregation=self.aggregation,
            composite_days=self.composite_days,
        )


class ResamplingPolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intensive_method: ResamplingMethod = "bilinear"
    extensive_method: ResamplingMethod = "sum"
    categorical_method: ResamplingMethod = "nearest"
    qa_method: ResamplingMethod = "nearest"

    def to_domain(self) -> ResamplingPolicy:
        return ResamplingPolicy(
            intensive_method=self.intensive_method,
            extensive_method=self.extensive_method,
            categorical_method=self.categorical_method,
            qa_method=self.qa_method,
        )


class HarmonizeRequest(BaseModel):
    """Input payload for submitting an async job or synchronous harmonization run."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    product: str = Field(min_length=1)
    request_payload: dict[str, object] = Field(default_factory=dict)
    target_grid: GridSpecIn | None = None
    target_temporal: TemporalSpecIn | None = None
    resampling_policy: ResamplingPolicyIn = Field(default_factory=ResamplingPolicyIn)
    variables: tuple[str, ...] = ()
    output_format: OutputFormat = "geotiff"
    max_attempts: int = Field(default=3, ge=1, le=10)

    def to_plan(self) -> HarmonizationPlan:
        return HarmonizationPlan(
            plan_id=uuid4(),
            provider=self.provider,
            product=self.product,
            request_payload=dict(self.request_payload),
            target_grid=self.target_grid.to_domain() if self.target_grid else None,
            target_temporal=self.target_temporal.to_domain() if self.target_temporal else None,
            resampling_policy=self.resampling_policy.to_domain(),
            variables=self.variables,
            output_format=self.output_format,
        )


class JobOut(BaseModel):
    job_id: UUID
    status: JobStatus
    provider: str
    product: str
    attempt: int
    max_attempts: int
    dataset_id: UUID | None = None
    error_message: str | None = None
    locked_by: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, job: HarmonizationJob) -> "JobOut":
        return cls(
            job_id=job.job_id,
            status=job.status,
            provider=job.plan.provider,
            product=job.plan.product,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            dataset_id=job.dataset_id,
            error_message=job.error_message,
            locked_by=job.locked_by,
            lease_expires_at=job.lease_expires_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class AssetOut(BaseModel):
    asset_id: str
    uri: str
    data_format: str
    media_type: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None


class QualityOut(BaseModel):
    passed: bool
    valid_fraction: float
    nodata_fraction: float
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @classmethod
    def from_domain(cls, qc: QualityReport) -> "QualityOut":
        return cls(
            passed=qc.passed,
            valid_fraction=qc.valid_fraction,
            nodata_fraction=qc.nodata_fraction,
            checks=qc.checks,
            warnings=qc.warnings,
            errors=qc.errors,
        )


class DatasetOut(BaseModel):
    dataset_id: UUID
    source_id: str
    provider: str
    product: str
    units: dict[str, str]
    variables: dict[str, object]
    spatial_metadata: dict[str, object]
    temporal_metadata: dict[str, object]
    quality_metadata: dict[str, object]
    assets: tuple[AssetOut, ...]
    provenance: dict[str, object]
    extensions: dict[str, object]

    @classmethod
    def from_domain(cls, dataset: SpatialDataset) -> "DatasetOut":
        from geospatial_harmonization.infrastructure.database.codec import encode_dataset

        raw = encode_dataset(dataset)
        return cls.model_validate(raw)


class ProcessingResultOut(BaseModel):
    job_id: UUID
    dataset: DatasetOut
    quality_report: QualityOut
    completed_at: datetime
    output_assets: tuple[AssetOut, ...]
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_domain(cls, result: ProcessingResult) -> "ProcessingResultOut":
        assets = tuple(
            AssetOut(
                asset_id=a.asset_id,
                uri=a.uri,
                data_format=a.data_format,
                media_type=a.media_type,
                checksum_sha256=a.checksum_sha256,
                size_bytes=a.size_bytes,
            )
            for a in result.output_assets
        )
        return cls(
            job_id=result.job_id,
            dataset=DatasetOut.from_domain(result.dataset),
            quality_report=QualityOut.from_domain(result.quality_report),
            completed_at=result.completed_at,
            output_assets=assets,
            warnings=result.warnings,
        )


class CapabilitiesOut(BaseModel):
    handlers: dict[str, tuple[str, ...]]
    formats: tuple[str, ...]


class ZoneUsageSummaryOut(BaseModel):
    zone: StorageZone
    object_count: int
    stored_bytes: int
    reserved_bytes: int
    original_bytes: int
    compression_saved_bytes: int
    dedup_saved_bytes: int


class StorageWarningOut(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    message: str
    action: str
    zone: StorageZone | None = None
    current_bytes: int | None = None
    threshold_bytes: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class StorageUsageOut(BaseModel):
    budget_bytes: int
    warning_threshold: float
    hard_limit_threshold: float
    hard_limit_bytes: int
    total_stored_bytes: int
    object_count: int
    reserved_bytes: int
    available_budget_bytes: int
    utilization_ratio: float
    zones: dict[StorageZone, ZoneUsageSummaryOut]
    daily_growth_bytes: int
    compression_savings_bytes: int
    deduplication_savings_bytes: int
    cleanup_deleted_objects: int
    cleanup_reclaimed_bytes: int
    failed_uploads_count: int
    orphaned_objects_count: int
    missing_referenced_objects_count: int
    reconciliation_diff_bytes: int | None = None
    warnings: tuple[StorageWarningOut, ...]
    measured_at: datetime

    @classmethod
    def from_domain(cls, summary: StorageUsageSummary) -> "StorageUsageOut":
        return cls.model_validate(asdict(summary))


class QuotaPolicyOut(BaseModel):
    budget_bytes: int
    warning_threshold: float
    hard_limit_threshold: float
    max_object_bytes: int
    max_job_output_bytes: int
    estimation_enabled: bool
    reservation_ttl_seconds: int


class ZonePolicyOut(BaseModel):
    retention_seconds: int | None = None
    auto_cleanup_on_job_success: bool
    immutable: bool
    allow_deduplication: bool


class CompressionPolicyOut(BaseModel):
    enabled: bool
    raster_codec: str
    raster_cog_enabled: bool
    raster_block_size: int
    netcdf_complevel: int
    zarr_codec: str
    zarr_target_chunk_bytes: int
    allow_lossy_compression: bool
    min_recompress_savings_ratio: float


class DeduplicationPolicyOut(BaseModel):
    enabled: bool
    verify_upload_integrity: bool


class LifecyclePolicyOut(BaseModel):
    orphan_grace_seconds: int
    abandoned_temp_max_age_seconds: int
    max_worker_concurrency: int
    temp_max_bytes: int


class StoragePolicyOut(BaseModel):
    storage_backend: str
    quota: QuotaPolicyOut
    zones: dict[StorageZone, ZonePolicyOut]
    compression: CompressionPolicyOut
    deduplication: DeduplicationPolicyOut
    lifecycle: LifecyclePolicyOut


class StorageHealthOut(BaseModel):
    status: Literal["ok", "warning", "critical"]
    storage_backend: str
    budget_bytes: int
    available_budget_bytes: int
    utilization_ratio: float
    orphaned_objects_count: int
    missing_referenced_objects_count: int
    warnings: tuple[StorageWarningOut, ...]
    checked_at: datetime


class ReconciliationReportOut(BaseModel):
    ledger_bytes: int
    actual_store_bytes: int
    bytes_difference: int
    ledger_object_count: int
    actual_store_object_count: int
    untracked_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    expired_reservations_reconciled: int
    warnings: tuple[StorageWarningOut, ...]
    checked_at: datetime

    @classmethod
    def from_domain(cls, report: ReconciliationReport) -> "ReconciliationReportOut":
        return cls.model_validate(asdict(report))


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    grace_seconds: int | None = Field(default=None, ge=0)
    include_expired_derived: bool = False


class CleanupReportOut(BaseModel):
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

    @classmethod
    def from_domain(cls, report: CleanupReport) -> "CleanupReportOut":
        return cls.model_validate(asdict(report))
