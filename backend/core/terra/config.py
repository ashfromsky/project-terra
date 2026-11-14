"""Centralized application settings.

Values are read from the process environment or from a `.env` file placed in
the working directory the server is started from. Environment files are never
committed; every field of `Settings` maps to an environment variable of the
same name (with the defaults documented below). Unknown variables (for
example frontend `VITE_*` entries) are ignored.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
_DEFAULT_DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-in-production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
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

    github_client_id: str = ""
    github_client_secret: SecretStr = SecretStr("")
    github_redirect_uri: str = "http://localhost:8000/api/v1/auth/github/callback"
    github_oauth_scopes: str = "read:user user:email"
    frontend_auth_redirect_url: str = "http://localhost:5173"

    jwt_secret_key: SecretStr = SecretStr(_DEFAULT_DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    auth_cookie_name: str = "terra_session"
    auth_cookie_secure: bool = False

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
            self.database_url = "sqlite+aiosqlite:///./terra.dev.db"
        if self.environment == "production":
            secret = self.jwt_secret_key.get_secret_value()
            if not secret or secret == _DEFAULT_DEV_JWT_SECRET or len(secret) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be set to a strong (>= 32 chars) secret in production"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
