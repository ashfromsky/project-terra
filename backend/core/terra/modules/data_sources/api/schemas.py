"""Pydantic request and response schemas for Core /data-sources endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from terra.api.schemas import CamelModel
from terra.modules.assessments.api.schemas import AssessmentReadinessResponse
from terra.modules.data_sources.domain.entities import IngestionOperationRecord

BBoxTuple = tuple[float, float, float, float]


class ProviderVariableSchema(CamelModel):
    """Variable metadata exposed by a registered GHS environmental provider."""

    name: str
    units: str
    semantics: str
    description: str


class ProviderProductSchema(CamelModel):
    """Product metadata registered in GHS."""

    product: str
    version: str
    title: str
    spatial_resolution: str
    temporal_resolution: str
    crs: str
    source_format: str
    variables: list[ProviderVariableSchema] = Field(default_factory=list)


class ProviderStatusResponse(CamelModel):
    """Capability, configuration, and credential readiness status of a GHS provider."""

    provider: str
    title: str
    enabled: bool
    auth_required: bool
    auth_configured: bool
    auth_mechanism: str
    status: str
    supports_discovery: bool
    registered_products: list[str] = Field(default_factory=list)
    products: list[ProviderProductSchema] = Field(default_factory=list)


class DiscoverObservationsRequest(CamelModel):
    """Discovery query parameters for searching real observations for an AOI."""

    provider: str = Field(..., min_length=1)
    product: str = Field(..., min_length=1)
    region_id: UUID | None = None
    bbox: BBoxTuple | None = None
    start_time: datetime
    end_time: datetime
    limit: int = Field(default=20, ge=1, le=50)


class DiscoveredObservationResponse(CamelModel):
    """Single candidate satellite granule or station observation."""

    observation_id: str
    provider: str
    product: str
    product_version: str
    title: str
    time_start: datetime | None = None
    time_end: datetime | None = None
    bbox: BBoxTuple | None = None
    query_mode: str | None = None
    access_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoverObservationsResponse(CamelModel):
    """Collection of candidate observations matching AOI and period."""

    provider: str
    product: str
    count: int
    bbox: BBoxTuple
    observations: list[DiscoveredObservationResponse] = Field(default_factory=list)


class StartIngestionRequest(CamelModel):
    """Request to launch bounded GHS ingestion and harmonization for an AOI."""

    provider: str = Field(..., min_length=1)
    product: str = Field(..., min_length=1)
    region_id: UUID | None = None
    bbox: BBoxTuple | None = None
    start_time: datetime
    end_time: datetime
    max_granules: int = Field(default=24, ge=1, le=256)
    variables: list[str] = Field(default_factory=list)
    target_cadence: str | None = None
    target_aggregation: str | None = None
    run_type: str | None = None
    overpass: str | None = None
    parameters: list[str] = Field(default_factory=list)
    community: str | None = None
    execute_now: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64)


class PreparedDatasetTimeSeriesPreviewSchema(CamelModel):
    """Reduced AOI time-series preview extracted from a prepared GHS dataset."""

    variable: str
    count: int
    start: str | None = None
    end: str | None = None
    units: str | None = None
    timestamps: list[str] = Field(default_factory=list)
    values: list[float | None] = Field(default_factory=list)


class PreparedDatasetSummaryResponse(CamelModel):
    """Summary and provenance view of a harmonized dataset stored in GHS."""

    dataset_id: str
    source_id: str
    provider: str
    product: str
    product_version: str | None = None
    granule_id: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    variables: list[str] = Field(default_factory=list)
    temporal_start: str | None = None
    temporal_end: str | None = None
    temporal_cadence: str | None = None
    temporal_semantics: str | None = None
    spatial_crs: str | None = None
    nominal_resolution_m: float | None = None
    observation_count: int = 0
    valid_fraction: float | None = None
    qa_policy: str | None = None
    qa_layers_present: list[str] = Field(default_factory=list)
    span_years: float | None = None
    region_id: UUID | None = None
    ingestion_operation_id: UUID | None = None
    warnings: list[str] = Field(default_factory=list)
    time_series_previews: list[PreparedDatasetTimeSeriesPreviewSchema] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    quality_metadata: dict[str, Any] = Field(default_factory=dict)
    spatial_metadata: dict[str, Any] = Field(default_factory=dict)
    temporal_metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionOperationResponse(CamelModel):
    """Persisted Core tracking record for a submitted GHS ingestion workflow."""

    id: UUID
    region_id: UUID | None = None
    ghs_job_id: str
    provider: str
    product: str
    status: str
    progress_pct: float
    dataset_id: str | None = None
    error_message: str | None = None
    error_category: str | None = None
    request_summary: dict[str, Any] = Field(default_factory=dict)
    dataset_summary: PreparedDatasetSummaryResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_domain(cls, record: IngestionOperationRecord) -> "IngestionOperationResponse":
        ds_summary = (
            PreparedDatasetSummaryResponse.model_validate(record.dataset_summary)
            if record.dataset_summary is not None
            else None
        )
        return cls(
            id=record.id,
            region_id=record.region_id,
            ghs_job_id=record.ghs_job_id,
            provider=record.provider,
            product=record.product,
            status=record.status,
            progress_pct=record.progress_pct,
            dataset_id=record.dataset_id,
            error_message=record.error_message,
            error_category=record.error_category,
            request_summary=dict(record.request_summary),
            dataset_summary=ds_summary,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class DatasetAssetDownloadUrlResponse(CamelModel):
    """Download descriptor for a prepared GHS/R2 dataset asset."""

    dataset_id: str
    asset_id: str
    storage_key: str
    filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    download_url: str
    presigned: bool
    expires_in: int | None = None


class AutoProvisionRequest(CamelModel):
    """Adaptive multi-source discovery and provisioning request for an AOI and window."""

    region_id: UUID | None = None
    bbox: BBoxTuple | None = None
    analysis_start: datetime
    analysis_end: datetime
    target_cadence: str = Field(default="monthly", min_length=1)
    baseline_type: str = Field(default="out_of_sample", min_length=1)
    reference_start: datetime | None = None
    reference_end: datetime | None = None
    min_reference_years: int = Field(default=3, ge=1, le=30)
    qa_level: str = Field(default="strict", min_length=1)
    existing_dataset_ids: list[str] = Field(default_factory=list)
    desired_domains: list[str] = Field(default_factory=lambda: ["climate", "vegetation"])
    max_granules_per_product: int = Field(default=48, ge=1, le=256)


class ProvisioningStepResponse(CamelModel):
    """Single domain/provider attempt during adaptive data provisioning."""

    domain: str
    provider: str
    product: str
    status: str
    dataset_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    detail: str


class AutoProvisionResponse(CamelModel):
    """Adaptive provisioning outcome, provisioned datasets, and readiness diagnostics."""

    bbox: BBoxTuple
    analysis_start: datetime
    analysis_end: datetime
    provision_start: datetime
    provision_end: datetime
    window_expanded: bool
    window_expansion_reason: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    datasets: list[PreparedDatasetSummaryResponse] = Field(default_factory=list)
    steps: list[ProvisioningStepResponse] = Field(default_factory=list)
    readiness: AssessmentReadinessResponse | None = None
