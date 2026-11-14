"""Tests for centralized settings parsing."""

import pytest

from terra.config import Settings


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(cors_origins="http://a.example:5173, http://b.example:3000")

    assert settings.cors_origins == [
        "http://a.example:5173",
        "http://b.example:3000",
    ]


def test_cors_origins_accept_explicit_list() -> None:
    settings = Settings(cors_origins=["http://a.example:5173"])

    assert settings.cors_origins == ["http://a.example:5173"]


def test_cors_origins_read_from_environment_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment path must accept comma-separated values; pydantic-settings
    would otherwise JSON-decode the raw string and crash at startup."""
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example:5173, http://b.example:3000")

    settings = Settings(environment="test")

    assert settings.cors_origins == [
        "http://a.example:5173",
        "http://b.example:3000",
    ]


def test_cors_origins_read_from_environment_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.example:5173"]')

    settings = Settings(environment="test")

    assert settings.cors_origins == ["http://a.example:5173"]


def test_unknown_environment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated environment variables (for example frontend `VITE_*`
    entries) must not break settings construction."""
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("TERRA_UNRELATED_VARIABLE", "value")

    settings = Settings(environment="test", cors_origins=[])

    assert settings.environment == "test"
    assert settings.cors_origins == []


def test_production_environment_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(environment="production")


def test_production_environment_accepts_strong_jwt_secret() -> None:
    settings = Settings(
        environment="production",
        jwt_secret_key="a" * 32,
    )
    assert settings.environment == "production"
