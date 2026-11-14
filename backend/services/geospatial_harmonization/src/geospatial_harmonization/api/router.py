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
    StorageLifecycleDep,
    StorageMonitoringDep,
    StorageQuotaDep,
)
from geospatial_harmonization.api.schemas import (
    CapabilitiesOut,
    CleanupReportOut,
    CleanupRequest,
    DatasetOut,
    DependencyHealth,
    HarmonizeRequest,
    HealthResponse,
    JobOut,
    ProcessingResultOut,
    ReadinessResponse,
    ReconciliationReportOut,
    StorageHealthOut,
    StoragePolicyOut,
    StorageUsageOut,
)
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob
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
async def list_capabilities(handlers: HandlersDep, readers: ReadersDep) -> CapabilitiesOut:
    """List supported providers, products, and format decoders."""
    return CapabilitiesOut(
        handlers=handlers.list_capabilities(),
        formats=readers.registered_formats(),
    )


@v1_router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    body: HarmonizeRequest,
    handlers: HandlersDep,
    jobs: JobRepoDep,
) -> JobOut:
    """Validate and enqueue an asynchronous harmonization job."""
    plan = body.to_plan()
    handlers.get(plan.provider, plan.product)
    now = datetime.now(UTC)
    job = HarmonizationJob(
        job_id=uuid4(),
        plan=plan,
        status="pending",
        created_at=now,
        updated_at=now,
        max_attempts=body.max_attempts,
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
