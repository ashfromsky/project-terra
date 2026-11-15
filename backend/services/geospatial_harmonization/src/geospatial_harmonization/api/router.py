"""FastAPI health and versioned business routers for GHS."""

import hmac
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from geospatial_harmonization import __version__
from geospatial_harmonization.api.dependencies import (
    DatasetRepoDep,
    EngineDep,
    HandlersDep,
    HarmonizationServiceDep,
    JobRepoDep,
    ReadersDep,
    SettingsDep,
    StorageDep,
    StorageLifecycleDep,
    StorageMonitoringDep,
    StorageQuotaDep,
)
from geospatial_harmonization.api.schemas import (
    CancelJobRequest,
    CapabilitiesOut,
    CleanupReportOut,
    CleanupRequest,
    DatasetOut,
    DatasetPointQueryResponse,
    DatasetProvenanceOut,
    DependencyHealth,
    DiscoveredObservationOut,
    DiscoverRequest,
    DiscoverResponse,
    HarmonizeRequest,
    HealthResponse,
    JobOut,
    ProcessingResultOut,
    ProviderStatusOut,
    ReadinessResponse,
    ReconciliationReportOut,
    StorageHealthOut,
    StoragePolicyOut,
    StorageUsageOut,
)
from geospatial_harmonization.application.raster_viz import (
    RasterAssetUnavailableError,
    RasterVariableNotFoundError,
    UnsupportedRasterFormatError,
    query_dataset_point,
    render_dataset_bbox,
    render_dataset_tile,
)
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ProviderDisabledError,
)
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob
from geospatial_harmonization.handlers.catalog import (
    DiscoverableHandler,
    build_provider_status_snapshots,
)
from geospatial_harmonization.infrastructure.database import check_database_health

health_router = APIRouter(tags=["health"])
v1_router = APIRouter(tags=["harmonization"])


@health_router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Report basic service liveness."""
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@health_router.get("/ready", response_model=ReadinessResponse)
async def ready(
    response: Response,
    settings: SettingsDep,
    engine: EngineDep,
) -> ReadinessResponse:
    """Verify database connectivity before marking instance ready."""
    db_ok = await check_database_health(engine)
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if db_ok else "not_ready",
        service=settings.app_name,
        version=__version__,
        checks={"database": DependencyHealth(status="ok" if db_ok else "unavailable")},
    )


@v1_router.get("/capabilities", response_model=CapabilitiesOut)
async def list_capabilities(
    settings: SettingsDep, handlers: HandlersDep, readers: ReadersDep
) -> CapabilitiesOut:
    """List supported providers, products, format decoders, and runtime readiness."""
    caps = handlers.list_capabilities()
    providers = tuple(
        ProviderStatusOut.from_snapshot(snap)
        for snap in build_provider_status_snapshots(settings, caps)
    )
    return CapabilitiesOut(
        handlers=caps,
        formats=readers.registered_formats(),
        providers=providers,
    )


@v1_router.get("/providers", response_model=list[ProviderStatusOut])
async def list_providers(settings: SettingsDep, handlers: HandlersDep) -> list[ProviderStatusOut]:
    """Inspect configured providers, supported products/variables, and health without secrets."""
    snapshots = build_provider_status_snapshots(settings, handlers.list_capabilities())
    return [ProviderStatusOut.from_snapshot(snap) for snap in snapshots]


@v1_router.post("/discover", response_model=DiscoverResponse)
async def discover_observations(
    body: DiscoverRequest,
    handlers: HandlersDep,
) -> DiscoverResponse:
    """Discover available provider observations or query eligibility for an AOI and period."""
    handler = handlers.get(body.provider, body.product)
    if not isinstance(handler, DiscoverableHandler):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Provider '{body.provider}' does not support observation discovery",
        )
    observations = await handler.discover(
        product=body.product,
        bbox=body.bbox,
        start_time=body.start_time,
        end_time=body.end_time,
        limit=body.limit,
    )
    return DiscoverResponse(
        provider=body.provider,
        product=body.product,
        count=len(observations),
        observations=tuple(DiscoveredObservationOut.from_domain(obs) for obs in observations),
    )


@v1_router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    body: HarmonizeRequest,
    settings: SettingsDep,
    handlers: HandlersDep,
    jobs: JobRepoDep,
) -> JobOut:
    """Validate and enqueue an asynchronous harmonization job with idempotency support."""
    plan = body.to_plan()
    handlers.get(plan.provider, plan.product)
    if not settings.is_provider_enabled(plan.provider):
        raise ProviderDisabledError(
            f"Provider '{plan.provider}' is disabled by configuration",
            provider=plan.provider,
        )
    idem_key = (
        body.idempotency_key.strip() if body.idempotency_key else plan.compute_idempotency_key()
    )
    if not body.allow_duplicate:
        existing = await jobs.get_by_idempotency_key(idem_key)
        if existing is not None and existing.status in ("pending", "running", "succeeded"):
            return JobOut.from_domain(existing)
    now = datetime.now(UTC)
    job = HarmonizationJob(
        job_id=uuid4(),
        plan=plan,
        status="pending",
        created_at=now,
        updated_at=now,
        max_attempts=body.max_attempts,
        idempotency_key=idem_key,
    )
    await jobs.create(job)
    return JobOut.from_domain(job)


@v1_router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, jobs: JobRepoDep) -> JobOut:
    """Inspect durable harmonization job status and linked dataset_id."""
    job = await jobs.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobOut.from_domain(job)


@v1_router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: UUID,
    jobs: JobRepoDep,
    body: CancelJobRequest | None = None,
) -> JobOut:
    """Cancel a pending or running harmonization job if not yet succeeded or failed."""
    existing = await jobs.get_by_id(job_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if existing.status in ("succeeded", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel job '{job_id}' in terminal status '{existing.status}'",
        )
    reason = body.reason if body is not None else "Cancelled by request"
    cancelled = await jobs.cancel(job_id, datetime.now(UTC), reason=reason)
    if cancelled is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobOut.from_domain(cancelled)


@v1_router.post("/harmonize", response_model=ProcessingResultOut)
async def run_harmonize(
    body: HarmonizeRequest,
    service: HarmonizationServiceDep,
) -> ProcessingResultOut:
    """Execute a harmonization plan synchronously and persist dataset metadata."""
    result = await service.execute_plan(body.to_plan())
    return ProcessingResultOut.from_domain(result)


@v1_router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(
    datasets: DatasetRepoDep,
    limit: int = Query(default=50, ge=1, le=200),
    provider: str | None = None,
) -> list[DatasetOut]:
    """List recently harmonized datasets ordered newest-first."""
    items = await datasets.list_recent(limit=limit, provider=provider)
    return [DatasetOut.from_domain(item) for item in items]


@v1_router.get("/datasets/{dataset_id}", response_model=DatasetOut)
async def get_dataset(dataset_id: UUID, datasets: DatasetRepoDep) -> DatasetOut:
    """Retrieve canonical metadata, QC summary, and asset references by ID."""
    ds = await datasets.get_by_id(dataset_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return DatasetOut.from_domain(ds)


@v1_router.get("/datasets/{dataset_id}/provenance", response_model=DatasetProvenanceOut)
async def get_dataset_provenance(
    dataset_id: UUID, datasets: DatasetRepoDep
) -> DatasetProvenanceOut:
    """Retrieve dataset lineage, scientific quality metrics, and redacted asset references."""
    ds = await datasets.get_by_id(dataset_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return DatasetProvenanceOut.from_domain(ds)


def _parse_bbox_param(raw_bbox: str) -> tuple[float, float, float, float]:
    parts = [part.strip() for part in raw_bbox.split(",")]
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must contain 4 comma-separated floats")
    try:
        min_x, min_y, max_x, max_y = (float(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="bbox coordinates must be valid numbers"
        ) from exc
    if min_x >= max_x or min_y >= max_y:
        raise HTTPException(
            status_code=422, detail="bbox min bounds must be strictly less than max bounds"
        )
    return (min_x, min_y, max_x, max_y)


@v1_router.get("/datasets/{dataset_id}/tiles/{z}/{x}/{y}.png")
async def get_dataset_tile(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    datasets: DatasetRepoDep,
    storage: StorageDep,
    readers: ReadersDep,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> Response:
    """Render an XYZ RGBA PNG tile from a raster dataset using nearest-neighbor sampling."""
    if z < 0 or z > 22:
        raise HTTPException(status_code=422, detail="Zoom z must be between 0 and 22")
    max_index = 2**z
    if x < 0 or x >= max_index or y < 0 or y >= max_index:
        raise HTTPException(status_code=422, detail="Tile coordinates out of range for zoom level")
    ds = await datasets.get_by_id(dataset_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        png_bytes = await render_dataset_tile(
            ds,
            storage,
            readers,
            z=z,
            x=x,
            y=y,
            variable=variable,
            timestamp=timestamp,
            colormap=colormap,
            vmin=vmin,
            vmax=vmax,
            unit_conversion=unit_conversion,
        )
    except RasterAssetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        UnsupportedRasterFormatError,
        RasterVariableNotFoundError,
        IncompatibleDatasetError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@v1_router.get("/datasets/{dataset_id}/render.png")
async def get_dataset_render_png(
    dataset_id: UUID,
    bbox: str,
    datasets: DatasetRepoDep,
    storage: StorageDep,
    readers: ReadersDep,
    crs: str = "EPSG:4326",
    width: int = 512,
    height: int = 512,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> Response:
    """Render a bounded RGBA PNG raster preview using nearest-neighbor resampling."""
    if width < 1 or width > 2048 or height < 1 or height > 2048:
        raise HTTPException(status_code=422, detail="width and height must be between 1 and 2048")
    parsed_bbox = _parse_bbox_param(bbox)
    ds = await datasets.get_by_id(dataset_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        png_bytes = await render_dataset_bbox(
            ds,
            storage,
            readers,
            bbox=parsed_bbox,
            crs=crs,
            width=width,
            height=height,
            variable=variable,
            timestamp=timestamp,
            colormap=colormap,
            vmin=vmin,
            vmax=vmax,
            unit_conversion=unit_conversion,
        )
    except RasterAssetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        UnsupportedRasterFormatError,
        RasterVariableNotFoundError,
        IncompatibleDatasetError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@v1_router.get("/datasets/{dataset_id}/point", response_model=DatasetPointQueryResponse)
async def get_dataset_point(
    dataset_id: UUID,
    lon: float,
    lat: float,
    datasets: DatasetRepoDep,
    storage: StorageDep,
    readers: ReadersDep,
    variable: str | None = None,
    timestamp: str | None = None,
    unit_conversion: str | None = None,
) -> DatasetPointQueryResponse:
    """Inspect exact native raster grid pixel value and QA metadata at WGS 84 (lon, lat)."""
    if lon < -180.0 or lon > 180.0 or lat < -90.0 or lat > 90.0:
        raise HTTPException(status_code=422, detail="lon/lat coordinates out of WGS 84 bounds")
    ds = await datasets.get_by_id(dataset_id)
    if ds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    try:
        payload = await query_dataset_point(
            ds,
            storage,
            readers,
            lon=lon,
            lat=lat,
            variable=variable,
            timestamp=timestamp,
            unit_conversion=unit_conversion,
        )
    except RasterAssetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        UnsupportedRasterFormatError,
        RasterVariableNotFoundError,
        IncompatibleDatasetError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DatasetPointQueryResponse.model_validate(
        {**payload, "dataset_id": str(payload["dataset_id"])}
    )


def _extract_admin_token(request: Request) -> str | None:
    header_token = request.headers.get("X-Admin-Token")
    if header_token:
        return header_token.strip()
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return None


def _require_admin_token(request: Request, settings: Settings) -> None:
    if settings.ghs_admin_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage admin operations require GHS_ADMIN_TOKEN to be configured",
        )
    expected = settings.ghs_admin_token.get_secret_value()
    provided = _extract_admin_token(request)
    if provided is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin authentication token",
        )
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin authentication token",
        )


@v1_router.get("/storage/usage", response_model=StorageUsageOut)
async def get_storage_usage(monitoring: StorageMonitoringDep) -> StorageUsageOut:
    """Inspect real-time storage ledger utilization, zones, savings, and warnings."""
    summary = await monitoring.get_usage_summary(now=datetime.now(UTC))
    return StorageUsageOut.from_domain(summary)


@v1_router.get("/storage/policy", response_model=StoragePolicyOut)
async def get_storage_policy(monitoring: StorageMonitoringDep) -> StoragePolicyOut:
    """Expose active storage budget, zone retention, compression, and concurrency policies."""
    return StoragePolicyOut.model_validate(monitoring.get_policy_summary())


@v1_router.get("/storage/health", response_model=StorageHealthOut)
async def get_storage_health(
    settings: SettingsDep,
    monitoring: StorageMonitoringDep,
) -> StorageHealthOut:
    """Evaluate storage health, budget headroom, orphan count, and integrity status."""
    now = datetime.now(UTC)
    usage = StorageUsageOut.from_domain(await monitoring.get_usage_summary(now=now))
    if usage.missing_referenced_objects_count > 0 or any(
        w.severity == "critical" for w in usage.warnings
    ):
        storage_status: Literal["ok", "warning", "critical"] = "critical"
    elif usage.orphaned_objects_count > 0 or any(w.severity == "warning" for w in usage.warnings):
        storage_status = "warning"
    else:
        storage_status = "ok"
    return StorageHealthOut(
        status=storage_status,
        storage_backend=settings.storage_backend,
        budget_bytes=usage.budget_bytes,
        available_budget_bytes=usage.available_budget_bytes,
        utilization_ratio=usage.utilization_ratio,
        orphaned_objects_count=usage.orphaned_objects_count,
        missing_referenced_objects_count=usage.missing_referenced_objects_count,
        warnings=usage.warnings,
        checked_at=usage.measured_at,
    )


@v1_router.post("/storage/reconcile", response_model=ReconciliationReportOut)
async def reconcile_storage(
    request: Request,
    settings: SettingsDep,
    quota: StorageQuotaDep,
) -> ReconciliationReportOut:
    """Admin: reconcile ledger objects/reservations with actual object storage."""
    _require_admin_token(request, settings)
    report = await quota.reconcile_ledger_with_store(now=datetime.now(UTC))
    return ReconciliationReportOut.from_domain(report)


@v1_router.post("/storage/cleanup", response_model=CleanupReportOut)
async def run_storage_cleanup(
    request: Request,
    settings: SettingsDep,
    lifecycle: StorageLifecycleDep,
    body: CleanupRequest | None = None,
) -> CleanupReportOut:
    """Admin: execute dry-run or live storage lifecycle mark-and-sweep cleanup."""
    _require_admin_token(request, settings)
    req = body or CleanupRequest()
    report = await lifecycle.run_maintenance_cycle(
        dry_run=req.dry_run,
        grace_seconds=req.grace_seconds,
        include_expired_derived=req.include_expired_derived,
        now=datetime.now(UTC),
    )
    return CleanupReportOut.from_domain(report)
