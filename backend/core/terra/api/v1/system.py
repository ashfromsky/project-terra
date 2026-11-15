"""System metadata endpoints under ``/api/v1/system``."""

from fastapi import APIRouter

from terra import __version__
from terra.api.dependencies import ObjectStorageDep, SettingsDep
from terra.api.schemas import SystemInfoResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info", response_model=SystemInfoResponse)
async def system_info(
    settings: SettingsDep,
    object_storage: ObjectStorageDep,
) -> SystemInfoResponse:
    """Return API version, runtime environment, and auth capability metadata."""
    return SystemInfoResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        api_v1_prefix=settings.api_v1_prefix,
        auth_provider="github",
        default_crs="EPSG:4326",
        github_oauth_configured=bool(
            settings.github_client_id and settings.github_client_secret.get_secret_value()
        ),
        dev_auth_enabled=settings.environment == "development",
        storage_backend=object_storage.backend_name,
    )
