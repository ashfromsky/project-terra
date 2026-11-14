"""Centralized settings for the Geospatial Harmonization Service.

Environment variables map directly to fields of ``Settings``; ``.env*`` files
are never committed to version control per ADR 0001.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
StorageBackend = Literal["local", "s3"]
RasterCompressionCodec = Literal["DEFLATE", "ZSTD"]
ZarrCompressionCodec = Literal["zstd", "gzip", "blosc"]


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

    ghs_storage_budget_bytes: int = Field(default=8_000_000_000, ge=1)
    ghs_storage_warning_threshold: float = Field(default=0.80, gt=0.0, le=1.0)
    ghs_storage_hard_limit_threshold: float = Field(default=1.00, gt=0.0, le=1.0)
    ghs_storage_max_object_bytes: int = Field(default=2_147_483_648, ge=1)
    ghs_storage_max_job_output_bytes: int = Field(default=1_073_741_824, ge=1)
    ghs_storage_estimation_enabled: bool = True
    ghs_storage_reservation_ttl_seconds: int = Field(default=3600, ge=1, le=604_800)

    ghs_storage_raw_retention_days: int | None = Field(default=None, ge=1)
    ghs_storage_intermediate_retention_seconds: int = Field(default=3600, ge=60, le=2_592_000)
    ghs_storage_derived_retention_days: int | None = Field(default=None, ge=1)
    ghs_storage_orphan_grace_seconds: int = Field(default=3600, ge=1, le=2_592_000)
    ghs_storage_abandoned_temp_max_age_seconds: int = Field(default=1800, ge=1, le=604_800)
    ghs_storage_excessive_reservation_threshold: float = Field(default=0.50, gt=0.0, le=1.0)
    ghs_storage_daily_growth_warning_bytes: int = Field(default=2_000_000_000, ge=1)

    ghs_storage_compression_enabled: bool = True
    ghs_storage_raster_codec: RasterCompressionCodec = "ZSTD"
    ghs_storage_raster_cog_enabled: bool = True
    ghs_storage_raster_block_size: int = Field(default=512, ge=16, le=4096)
    ghs_storage_netcdf_complevel: int = Field(default=4, ge=1, le=9)
    ghs_storage_zarr_codec: ZarrCompressionCodec = "zstd"
    ghs_storage_zarr_target_chunk_bytes: int = Field(default=1_048_576, ge=4096, le=67_108_864)
    ghs_storage_allow_lossy_compression: bool = False
    ghs_storage_min_recompress_savings_ratio: float = Field(default=0.05, ge=0.0, lt=1.0)

    ghs_storage_dedup_enabled: bool = True
    ghs_storage_verify_upload_integrity: bool = True
    ghs_storage_stream_chunk_bytes: int = Field(default=1_048_576, ge=4096, le=16_777_216)
    ghs_storage_max_worker_concurrency: int = Field(default=2, ge=1, le=64)
    ghs_storage_temp_dir: Path | None = None
    ghs_storage_temp_max_bytes: int = Field(default=4_294_967_296, ge=1_048_576)

    ghs_admin_token: SecretStr | None = None

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

    @model_validator(mode="after")
    def _validate_storage_constraints(self) -> "Settings":
        if self.ghs_storage_warning_threshold > self.ghs_storage_hard_limit_threshold:
            raise ValueError(
                "ghs_storage_warning_threshold cannot exceed ghs_storage_hard_limit_threshold"
            )
        if self.ghs_storage_raster_block_size % 16 != 0:
            raise ValueError("ghs_storage_raster_block_size must be a multiple of 16")
        return self

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
