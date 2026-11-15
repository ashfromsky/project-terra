"""Smoke and configuration tests for Geospatial Harmonization Service."""

import pytest
from pydantic import ValidationError

from geospatial_harmonization import __version__
from geospatial_harmonization.config import Settings


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_default_settings_use_expected_service_conventions(test_settings: Settings) -> None:
    assert test_settings.api_v1_prefix == "/api/v1"
    assert test_settings.storage_backend == "local"
    assert test_settings.generic_handler_allowed_hosts == []


def test_list_settings_accept_csv_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://terra.example")
    monkeypatch.setenv("GENERIC_HANDLER_ALLOWED_HOSTS", '["data.nasa.gov","api.example.org"]')

    settings = Settings(_env_file=None, environment="test")

    assert settings.cors_origins == ["http://localhost:5173", "https://terra.example"]
    assert settings.generic_handler_allowed_hosts == ["data.nasa.gov", "api.example.org"]


def test_earthdata_token_is_masked_and_unknown_vars_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EARTHDATA_TOKEN", "edl-secret-token-value")
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8000")

    settings = Settings(_env_file=None, environment="test")

    assert "edl-secret-token-value" not in repr(settings)
    assert "edl-secret-token-value" not in str(settings)
    assert settings.earthdata_token is not None
    assert settings.earthdata_token.get_secret_value() == "edl-secret-token-value"


def test_invalid_bounds_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, http_timeout_seconds=-1.0)


def test_provider_enable_flags_and_token_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODIS_ENABLED", "false")
    monkeypatch.setenv("GPM_ENABLED", "true")
    monkeypatch.setenv("SMAP_ENABLED", "false")
    monkeypatch.setenv("NASA_POWER_ENABLED", "true")
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)

    settings = Settings(_env_file=None, environment="test")

    assert settings.is_provider_enabled("modis") is False
    assert settings.is_provider_enabled("gpm_imerg") is True
    assert settings.is_provider_enabled("gpm") is True
    assert settings.is_provider_enabled("smap") is False
    assert settings.is_provider_enabled("nasa_power") is True
    assert settings.is_provider_enabled("generic") is False
    assert settings.has_earthdata_token() is False

    settings_with_creds = Settings(
        _env_file=None,
        environment="test",
        earthdata_token="my-token",
        generic_handler_allowed_hosts=["data.nasa.gov"],
    )
    assert settings_with_creds.has_earthdata_token() is True
    assert settings_with_creds.is_provider_enabled("generic") is True
