"""API response schemas shared across API versions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base schema serializing camelCase JSON while accepting Python snake_case."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class HealthResponse(BaseModel):
    """Health probe payload."""

    status: str
    service: str
    version: str


class DependencyHealth(BaseModel):
    """Status of a single runtime dependency."""

    status: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    """Readiness probe payload reporting dependency availability."""

    status: Literal["ready", "not_ready"]
    service: str
    version: str
    checks: dict[str, DependencyHealth]


class SystemInfoResponse(CamelModel):
    """Version, environment, and capability metadata for the API."""

    service: str
    version: str
    environment: str
    api_v1_prefix: str
    auth_provider: str
    default_crs: str
    github_oauth_configured: bool
    dev_auth_enabled: bool = False
    storage_backend: str = "local"
