"""Centralized application settings.

Values are read from the process environment or from a `.env` file placed in
the working directory the server is started from (see `.env.example` at the
repository root). Unknown variables (for example `VITE_*` entries when the
root example file is copied verbatim) are ignored.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TERRA Core API"
    environment: Environment = "development"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"

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


@lru_cache
def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    return Settings()
