"""Tests for centralized settings parsing."""

from pathlib import Path

import pytest

from terra.config import Settings


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.example:5173, http://b.example:3000")

    assert settings.cors_origins == [
        "http://a.example:5173",
        "http://b.example:3000",
    ]


def test_cors_origins_accept_explicit_list() -> None:
    settings = Settings(_env_file=None, cors_origins=["http://a.example:5173"])

    assert settings.cors_origins == ["http://a.example:5173"]


def test_cors_origins_read_from_environment_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment path must accept comma-separated values; pydantic-settings
    would otherwise JSON-decode the raw string and crash at startup."""
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example:5173, http://b.example:3000")

    settings = Settings(_env_file=None, environment="test")

    assert settings.cors_origins == [
        "http://a.example:5173",
        "http://b.example:3000",
    ]


def test_cors_origins_read_from_environment_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.example:5173"]')

    settings = Settings(_env_file=None, environment="test")

    assert settings.cors_origins == ["http://a.example:5173"]


def test_unknown_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated environment variables (for example frontend `VITE_*`
    entries) must not break settings construction."""
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("TERRA_UNRELATED_VARIABLE", "value")

    settings = Settings(_env_file=None, environment="test", cors_origins=[])

    assert settings.environment == "test"
    assert settings.cors_origins == []


def test_production_environment_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="production")


def test_production_environment_accepts_strong_jwt_secret() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret_key="a" * 32,
    )
    assert settings.environment == "production"


def test_development_defaults_to_file_sqlite_and_ghs_url_when_unset() -> None:
    dev_settings = Settings(_env_file=None, environment="development")
    dev_db_path = (Path(__file__).resolve().parents[3] / ".data" / "terra.db").resolve()
    expected_db = f"sqlite+aiosqlite:///{dev_db_path}"
    assert dev_settings.database_url == expected_db
    assert dev_settings.ghs_base_url == "http://127.0.0.1:8080"
    assert dev_settings.ghs_timeout_seconds == 60.0

    explicit_settings = Settings(
        _env_file=None,
        environment="development",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    assert explicit_settings.database_url == "sqlite+aiosqlite:///:memory:"
