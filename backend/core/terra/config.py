"""Centralized application settings.

Values are read from the process environment or from a `.env` file placed in
the working directory the server is started from. Environment files are never
committed; every field of `Settings` maps to an environment variable of the
same name (with the defaults documented below). Unknown variables (for
example frontend `VITE_*` entries) are ignored.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
StorageBackend = Literal["local", "s3"]
_DEFAULT_DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-in-production"
_REPO_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger("terra.config")


def normalize_s3_endpoint_url(endpoint_url: str | None, bucket: str | None = None) -> str | None:
    """Normalize custom S3/R2 endpoint URL and strip accidental trailing bucket path."""
    if endpoint_url is None:
        return None
    cleaned = endpoint_url.strip().rstrip("/")
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    path = parsed.path.rstrip("/")
    if bucket and path == f"/{bucket.strip()}":
        logger.warning(
            "Stripping trailing bucket segment '/%s' from S3_ENDPOINT_URL.",
            bucket.strip(),
        )
        path = ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _default_dev_database_url() -> str:
    return f"sqlite+aiosqlite:///{(_REPO_ROOT / '.data' / 'terra.db').resolve()}"


def _default_dev_artifact_dir() -> str:
    return str((_REPO_ROOT / ".data" / "artifacts").resolve())


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TERRA Core API"
    environment: Environment = "development"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///:memory:"
    database_echo: bool = False
    database_auto_create_tables: bool = True

    ghs_base_url: str = "http://127.0.0.1:8080"
    ghs_timeout_seconds: float = 60.0
    scientific_artifact_dir: str | None = None
    terra_worker_poll_seconds: float = Field(default=2.0, gt=0.0, le=60.0)

    storage_backend: StorageBackend = "local"
    s3_bucket: str | None = None
    core_s3_prefix: str = "core"
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_presign_ttl_seconds: int = Field(default=300, ge=30, le=86_400)
    s3_connect_timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    s3_read_timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)
    s3_max_attempts: int = Field(default=4, ge=1, le=10)

    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    github_redirect_uri: str = "http://localhost:8000/api/v1/auth/github/callback"
    github_oauth_scopes: str = "read:user user:email"
    frontend_auth_redirect_url: str = "http://localhost:5173"
    # Optional directory containing a built SPA (index.html + assets/).
    # When set, Core serves the frontend from the same origin as the API.
    frontend_dist_dir: str | None = None

    jwt_secret_key: SecretStr = SecretStr(_DEFAULT_DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    auth_cookie_name: str = "terra_session"
    auth_cookie_secure: bool = False
    auto_researcher_session: bool = False

    # `NoDecode` keeps the raw string from env/dotenv sources so the validator
    # below can accept both JSON arrays and comma-separated lists. Without it,
    # pydantic-settings would attempt `json.loads` on every string value and
    # reject plain `CORS_ORIGINS=host1,host2` forms.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    cors_allow_credentials: bool = False
    cors_allow_methods: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    @field_validator("cors_origins", "cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def _parse_list_value(cls, value: Any) -> Any:
        """Accept JSON arrays or comma-separated strings for list-typed fields."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Apply safe dev storage default and reject insecure production secrets."""
        if self.environment == "development" and "database_url" not in self.model_fields_set:
            self.database_url = _default_dev_database_url()
        if (
            self.environment == "development"
            and "scientific_artifact_dir" not in self.model_fields_set
            and self.scientific_artifact_dir is None
        ):
            self.scientific_artifact_dir = _default_dev_artifact_dir()
        if self.database_url.startswith("sqlite+aiosqlite:///./"):
            rel_part = self.database_url.removeprefix("sqlite+aiosqlite:///./")
            self.database_url = f"sqlite+aiosqlite:///{(_REPO_ROOT / rel_part).resolve()}"
        if self.environment == "test" and "ghs_timeout_seconds" not in self.model_fields_set:
            self.ghs_timeout_seconds = 0.05
        if self.environment == "production":
            secret = self.jwt_secret_key.get_secret_value()
            if not secret or secret == _DEFAULT_DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be set to a strong (>= 32 chars) secret in production"
                )
        return self

    def effective_s3_access_key_id(self) -> str | None:
        """Resolve S3/R2 access key from ``S3_ACCESS_KEY_ID`` or ``AWS_ACCESS_KEY_ID``."""
        for candidate in (self.s3_access_key_id, self.aws_access_key_id):
            if candidate is not None and candidate.get_secret_value().strip():
                return candidate.get_secret_value().strip()
        return None

    def effective_s3_secret_access_key(self) -> str | None:
        """Resolve S3/R2 secret key from ``S3_SECRET_ACCESS_KEY`` or ``AWS_SECRET_ACCESS_KEY``."""
        for candidate in (self.s3_secret_access_key, self.aws_secret_access_key):
            if candidate is not None and candidate.get_secret_value().strip():
                return candidate.get_secret_value().strip()
        return None


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
