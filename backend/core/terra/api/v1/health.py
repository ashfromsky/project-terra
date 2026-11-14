"""Health probe under the versioned ``/api/v1`` surface."""

from fastapi import APIRouter

from terra import __version__
from terra.api.dependencies import SettingsDep
from terra.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Report service liveness."""
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)
