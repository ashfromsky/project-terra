"""Root health, liveness, and readiness probes (unversioned)."""

from fastapi import APIRouter, Response, status

from terra import __version__
from terra.api.dependencies import DatabaseManagerDep, ObjectStorageDep, SettingsDep
from terra.api.schemas import DependencyHealth, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Report basic service health."""
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@router.get("/health/live", response_model=HealthResponse)
async def health_live(settings: SettingsDep) -> HealthResponse:
    """Report process liveness without external dependency checks."""
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


@router.get("/health/ready", response_model=ReadinessResponse)
async def health_ready(
    response: Response,
    settings: SettingsDep,
    db: DatabaseManagerDep,
    object_storage: ObjectStorageDep,
) -> ReadinessResponse:
    """Verify runtime dependency readiness (database and object storage connectivity)."""
    db_ok = await db.check_readiness()
    storage_ok = await object_storage.check_health()
    all_ok = db_ok and storage_ok
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if all_ok else "not_ready",
        service=settings.app_name,
        version=__version__,
        checks={
            "database": DependencyHealth(status="ok" if db_ok else "unavailable"),
            "object_storage": DependencyHealth(status="ok" if storage_ok else "unavailable"),
        },
    )
