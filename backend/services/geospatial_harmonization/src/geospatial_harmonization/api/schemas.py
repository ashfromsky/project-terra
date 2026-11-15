"""Pydantic request and response schemas for the Geospatial Harmonization REST API."""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geospatial_harmonization.domain.exceptions import ErrorCategory
from geospatial_harmonization.domain.models.dataset import AssetReference, SpatialDataset
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
from geospatial_harmonization.handlers.catalog import (
    DiscoveryResult,
    ProviderHealthState,
    ProviderStatusSnapshot,
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
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64)
    allow_duplicate: bool = False

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


class CancelJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="Cancelled by request", min_length=1, max_length=256)


class JobOut(BaseModel):
    job_id: UUID
    status: JobStatus
    provider: str
    product: str
    attempt: int
    max_attempts: int
    dataset_id: UUID | None = None
    error_message: str | None = None
    error_category: ErrorCategory | None = None
    next_retry_at: datetime | None = None
    progress_pct: int = 0
    idempotency_key: str | None = None
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
            error_category=job.error_category,
            next_retry_at=job.next_retry_at,
            progress_pct=job.progress_pct,
            idempotency_key=job.idempotency_key,
            locked_by=job.locked_by,
            lease_expires_at=job.lease_expires_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


def _sanitize_asset_uri(uri: str | None) -> str | None:
    if uri is None:
        return None
    if uri.startswith(("file://", "s3://", "/")):
        return None
    return uri


def _sanitize_source_url(url: str) -> str:
    if url.startswith("file://"):
        name = Path(url.removeprefix("file://")).name or "local-asset"
        return f"local://{name}"
    return url


def _sanitize_provenance_dict(provenance_raw: object) -> dict[str, object]:
    if not isinstance(provenance_raw, dict):
        return {}
    clean = dict(provenance_raw)
    raw_urls = clean.get("source_urls")
    if isinstance(raw_urls, list):
        clean["source_urls"] = [_sanitize_source_url(str(u)) for u in raw_urls]
    return clean


class AssetOut(BaseModel):
    asset_id: str
    uri: str | None = None
    storage_key: str | None = None
    zone: str | None = None
    data_format: str
    media_type: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None

    @classmethod
    def from_domain(cls, asset: AssetReference) -> "AssetOut":
        return cls(
            asset_id=asset.asset_id,
            uri=_sanitize_asset_uri(asset.uri),
            storage_key=asset.storage_key,
            zone=asset.zone,
            data_format=asset.data_format,
            media_type=asset.media_type,
            checksum_sha256=asset.checksum_sha256,
            size_bytes=asset.size_bytes,
        )


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
    product_version: str | None = None
    granule_id: str | None = None
    units: dict[str, str]
    variables: dict[str, object]
    spatial_metadata: dict[str, object]
    temporal_metadata: dict[str, object]
    quality_metadata: dict[str, object]
    assets: tuple[AssetOut, ...]
    provenance: dict[str, object]
    extensions: dict[str, object]
    bbox_wgs84: tuple[float, float, float, float] | None = None

    @classmethod
    def from_domain(cls, dataset: SpatialDataset) -> "DatasetOut":
        from rasterio.warp import transform_bounds

        from geospatial_harmonization.infrastructure.database.codec import encode_dataset

        raw = encode_dataset(dataset)
        raw["assets"] = [AssetOut.from_domain(a).model_dump() for a in dataset.assets]
        raw["provenance"] = _sanitize_provenance_dict(raw.get("provenance"))

        bbox_wgs84: tuple[float, float, float, float] | None = None
        bounds = dataset.spatial_metadata.bounds
        crs = dataset.spatial_metadata.crs
        if bounds is None and dataset.spatial_metadata.grid is not None:
            bounds = dataset.spatial_metadata.grid.bounds
            crs = dataset.spatial_metadata.grid.crs
        if bounds is not None:
            if crs is None or "4326" in crs:
                bbox_wgs84 = bounds.as_tuple()
            else:
                try:
                    w, s, e, n = transform_bounds(
                        crs, "EPSG:4326", *bounds.as_tuple(), densify_pts=21
                    )
                    bbox_wgs84 = (float(w), float(s), float(e), float(n))
                except Exception:
                    bbox_wgs84 = None
        raw["bbox_wgs84"] = bbox_wgs84
        return cls.model_validate(raw)


class DatasetProvenanceOut(BaseModel):
    dataset_id: UUID
    source_id: str
    granule_id: str | None = None
    provider: str
    product: str
    product_version: str | None = None
    spatial_metadata: dict[str, object]
    temporal_metadata: dict[str, object]
    quality_metadata: dict[str, object]
    provenance: dict[str, object]
    assets: tuple[AssetOut, ...]

    @classmethod
    def from_domain(cls, dataset: SpatialDataset) -> "DatasetProvenanceOut":
        ds_out = DatasetOut.from_domain(dataset)
        return cls(
            dataset_id=ds_out.dataset_id,
            source_id=ds_out.source_id,
            granule_id=ds_out.granule_id,
            provider=ds_out.provider,
            product=ds_out.product,
            product_version=ds_out.product_version,
            spatial_metadata=ds_out.spatial_metadata,
            temporal_metadata=ds_out.temporal_metadata,
            quality_metadata=ds_out.quality_metadata,
            provenance=ds_out.provenance,
            assets=ds_out.assets,
        )


class ProcessingResultOut(BaseModel):
    job_id: UUID
    dataset: DatasetOut
    quality_report: QualityOut
    completed_at: datetime
    output_assets: tuple[AssetOut, ...]
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_domain(cls, result: ProcessingResult) -> "ProcessingResultOut":
        assets = tuple(AssetOut.from_domain(a) for a in result.output_assets)
        return cls(
            job_id=result.job_id,
            dataset=DatasetOut.from_domain(result.dataset),
            quality_report=QualityOut.from_domain(result.quality_report),
            completed_at=result.completed_at,
            output_assets=assets,
            warnings=result.warnings,
        )


class VariableInfoOut(BaseModel):
    name: str
    units: str
    semantics: str
    description: str


class ProductInfoOut(BaseModel):
    product: str
    version: str
    title: str
    spatial_resolution: str
    temporal_resolution: str
    crs: str
    source_format: str
    variables: tuple[VariableInfoOut, ...]


class ProviderStatusOut(BaseModel):
    provider: str
    title: str
    enabled: bool
    auth_required: bool
    auth_configured: bool
    auth_mechanism: str
    status: ProviderHealthState
    supports_discovery: bool
    registered_products: tuple[str, ...]
    products: tuple[ProductInfoOut, ...]

    @classmethod
    def from_snapshot(cls, snap: ProviderStatusSnapshot) -> "ProviderStatusOut":
        return cls.model_validate(asdict(snap))


class CapabilitiesOut(BaseModel):
    handlers: dict[str, tuple[str, ...]]
    formats: tuple[str, ...]
    providers: tuple[ProviderStatusOut, ...] = ()


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    product: str = Field(min_length=1)
    bbox: tuple[float, float, float, float]
    start_time: datetime
    end_time: datetime
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _validate_window_and_bbox(self) -> "DiscoverRequest":
        min_lon, min_lat, max_lon, max_lat = self.bbox
        if not (-180.0 <= min_lon < max_lon <= 180.0):
            raise ValueError("bbox longitudes must satisfy -180 <= min_lon < max_lon <= 180")
        if not (-90.0 <= min_lat < max_lat <= 90.0):
            raise ValueError("bbox latitudes must satisfy -90 <= min_lat < max_lat <= 90")
        if self.end_time < self.start_time:
            raise ValueError("end_time cannot precede start_time")
        return self


class DiscoveredObservationOut(BaseModel):
    observation_id: str
    provider: str
    product: str
    product_version: str
    title: str
    time_start: datetime | None = None
    time_end: datetime | None = None
    bbox: tuple[float, float, float, float] | None = None
    query_mode: str | None = None
    access_hint: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, item: DiscoveryResult) -> "DiscoveredObservationOut":
        return cls(
            observation_id=item.observation_id,
            provider=item.provider,
            product=item.product,
            product_version=item.product_version,
            title=item.title,
            time_start=item.time_start,
            time_end=item.time_end,
            bbox=item.bbox,
            query_mode=item.query_mode,
            access_hint=item.access_hint,
            metadata=dict(item.metadata or {}),
        )


class DiscoverResponse(BaseModel):
    provider: str
    product: str
    count: int
    observations: tuple[DiscoveredObservationOut, ...]


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


class RasterPointBBoxOut(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


class DatasetPointSeriesPointOut(BaseModel):
    timestamp: str
    value: float | None = None


class DatasetPointQueryResponse(BaseModel):
    dataset_id: str
    product: str
    variable: str
    lon: float
    lat: float
    timestamp: str
    status: str
    value: float | None = None
    raw_value: float | None = None
    unit: str | None = None
    qa_value: int | None = None
    qa_passed: bool | None = None
    crs: str
    nominal_resolution_m: float | None = None
    pixel_row: int | None = None
    pixel_col: int | None = None
    bbox: RasterPointBBoxOut
    time_series: list[DatasetPointSeriesPointOut] = []


class DerivedDatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str = Field(min_length=1, max_length=128)
    variable_name: str = Field(min_length=1, max_length=128)
    units: str = Field(min_length=1, max_length=64)
    bbox_wgs84: tuple[float, float, float, float]
    scope: Literal["grid", "aoi"] = "aoi"
    values_2d: list[list[float | None]] | None = None
    scalar_value: float | None = None
    aoi_geojson: dict[str, object] | None = None
    temporal_start: datetime | None = None
    temporal_end: datetime | None = None
    timestamps: list[str] = Field(default_factory=list)
    time_series_values: list[float | None] = Field(default_factory=list)
    source_dataset_ids: list[str] = Field(default_factory=list)
    qa_policy: str | None = None
    method_version: str = "1.0.0"


class AssetDownloadUrlOut(BaseModel):
    dataset_id: UUID
    asset_id: str
    storage_key: str | None = None
    filename: str
    media_type: str
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    download_url: str
    presigned: bool
    expires_in: int | None = None
