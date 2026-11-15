"""Centralized settings for the Geospatial Harmonization Service.

Environment variables map directly to fields of ``Settings``; ``.env*`` files
are never committed to version control per ADR 0001.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
StorageBackend = Literal["local", "s3"]
RasterCompressionCodec = Literal["DEFLATE", "ZSTD"]
ZarrCompressionCodec = Literal["zstd", "gzip", "blosc"]

_PROVIDER_ALIAS_MAP: dict[str, str] = {
    "modis": "modis",
    "gpm": "gpm_imerg",
    "gpm_imerg": "gpm_imerg",
    "smap": "smap",
    "nasa_power": "nasa_power",
    "generic": "generic",
}


def _resolve_env_files() -> tuple[Path, ...]:
    """Discover repo-root, service-root, and cwd `.env` files in increasing priority."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in reversed(here.parents):
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            env_path = parent / ".env"
            if env_path not in candidates:
                candidates.append(env_path)
    cwd_env = Path(".env")
    if cwd_env not in candidates:
        candidates.append(cwd_env)
    return tuple(candidates)


class Settings(BaseSettings):
    """Typed service configuration loaded from process environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(),
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
    ghs_database_url: str | None = None
    database_echo: bool = False

    storage_backend: StorageBackend = "local"
    local_storage_dir: Path = Path("./.ghs_storage")
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    _init_database_url_provided: bool = PrivateAttr(default=False)

    def __init__(self, **data: Any) -> None:
        explicit_db = "database_url" in data
        super().__init__(**data)
        if not explicit_db and self.ghs_database_url and self.ghs_database_url.strip():
            self.database_url = self.ghs_database_url.strip()
        self._init_database_url_provided = explicit_db

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
    modis_enabled: bool = True
    gpm_enabled: bool = True
    smap_enabled: bool = True
    nasa_power_enabled: bool = True
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api"
    cmr_base_url: str = "https://cmr.earthdata.nasa.gov/search"
    appeears_base_url: str = "https://appeears.earthdatacloud.nasa.gov/api"
    generic_handler_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    earthdata_presigned_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["*.cloudfront.net", "*.amazonaws.com"]
    )

    http_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    http_retry_backoff_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    http_max_download_bytes: int = Field(default=2_147_483_648, ge=1)
    worker_poll_interval_seconds: float = Field(default=2.0, gt=0.0, le=60.0)
    ghs_worker_poll_seconds: float | None = Field(default=None, gt=0.0, le=60.0)
    worker_lease_seconds: int = Field(default=300, ge=30, le=86400)
    max_grid_pixels: int = Field(default=100_000_000, ge=1)

    @model_validator(mode="after")
    def _validate_storage_constraints(self) -> "Settings":
        if self.ghs_worker_poll_seconds is not None:
            self.worker_poll_interval_seconds = self.ghs_worker_poll_seconds
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
        "earthdata_presigned_hosts",
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

    def has_earthdata_token(self) -> bool:
        """Return True when a non-empty Earthdata credential is configured without exposing it."""
        return bool(self.earthdata_token and self.earthdata_token.get_secret_value().strip())

    def effective_s3_access_key_id(self) -> str | None:
        """Return non-empty AWS or S3 access key ID without exposing SecretStr in repr."""
        token = self.aws_access_key_id or self.s3_access_key_id
        if token is None:
            return None
        value = token.get_secret_value().strip()
        return value or None

    def effective_s3_secret_access_key(self) -> str | None:
        """Return non-empty AWS or S3 secret access key without exposing SecretStr in repr."""
        token = self.aws_secret_access_key or self.s3_secret_access_key
        if token is None:
            return None
        value = token.get_secret_value().strip()
        return value or None

    def is_provider_enabled(self, provider: str) -> bool:
        """Return whether the given provider is enabled by configuration."""
        canonical = _PROVIDER_ALIAS_MAP.get(provider.strip().lower(), provider.strip().lower())
        flags: dict[str, bool] = {
            "modis": self.modis_enabled,
            "gpm_imerg": self.gpm_enabled,
            "smap": self.smap_enabled,
            "nasa_power": self.nasa_power_enabled,
            "generic": bool(self.generic_handler_allowed_hosts),
        }
        return flags.get(canonical, False)


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
