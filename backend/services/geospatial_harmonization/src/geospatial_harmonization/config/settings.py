"""Centralized settings for the Geospatial Harmonization Service.

Environment variables map directly to fields of ``Settings``; ``.env*`` files
are never committed to version control per ADR 0001.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
StorageBackend = Literal["local", "s3"]


class Settings(BaseSettings):
    """Typed service configuration loaded from process environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TERRA Geospatial Harmonization Service"
    environment: Environment = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # `NoDecode` keeps raw env strings intact so the validator accepts both JSON arrays and CSV.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    cors_allow_credentials: bool = False
    cors_allow_methods: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    database_url: str = "sqlite+aiosqlite:///./ghs.db"
    database_echo: bool = False

    storage_backend: StorageBackend = "local"
    local_storage_dir: Path = Path("./.ghs_storage")
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"

    earthdata_token: SecretStr | None = None
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api"
    cmr_base_url: str = "https://cmr.earthdata.nasa.gov/search"
    appeears_base_url: str = "https://appeears.earthdatacloud.nasa.gov/api"
    generic_handler_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)

    http_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    worker_poll_interval_seconds: float = Field(default=2.0, gt=0.0, le=60.0)
    worker_lease_seconds: int = Field(default=300, ge=30, le=86400)
    max_grid_pixels: int = Field(default=100_000_000, ge=1)

    @field_validator(
        "cors_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "generic_handler_allowed_hosts",
        mode="before",
    )
    @classmethod
    def _parse_list_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
