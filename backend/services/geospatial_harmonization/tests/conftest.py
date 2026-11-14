"""Shared pytest fixtures for Geospatial Harmonization Service tests."""

import pytest

from geospatial_harmonization.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Deterministic test settings independent of any local `.env`."""
    return Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=[],
    )
