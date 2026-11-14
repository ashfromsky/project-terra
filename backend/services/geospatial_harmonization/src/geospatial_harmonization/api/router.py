"""FastAPI health and versioned business routers for GHS."""

from fastapi import APIRouter, Response, status

from geospatial_harmonization import __version__
from geospatial_harmonization.api.dependencies import EngineDep, SettingsDep
from geospatial_harmonization.api.schemas import DependencyHealth, HealthResponse, ReadinessResponse
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
