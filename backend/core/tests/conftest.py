"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests, independent of any local `.env`."""
    return Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=[],
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Test client with the application lifespan running."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def cors_client() -> Iterator[TestClient]:
    """Test client for an application configured with CORS origins enabled."""
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            cors_origins=["http://localhost:5173"],
        )
    )
    with TestClient(app) as test_client:
        yield test_client
