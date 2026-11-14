"""FastAPI health and versioned business routers for GHS."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status

from geospatial_harmonization import __version__
from geospatial_harmonization.api.dependencies import (
    DatasetRepoDep,
    EngineDep,
    HandlersDep,
    HarmonizationServiceDep,
    JobRepoDep,
    ReadersDep,
    SettingsDep,
)
from geospatial_harmonization.api.schemas import (
    CapabilitiesOut,
    DatasetOut,
    DependencyHealth,
    HarmonizeRequest,
    HealthResponse,
    JobOut,
    ProcessingResultOut,
    ReadinessResponse,
)
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
