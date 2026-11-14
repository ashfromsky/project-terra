"""Tests for system probes, readiness checks, and system info endpoints."""

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app


def test_health_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"]
    assert payload["version"]


def test_health_ready_returns_ready_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["status"] == "ok"


def test_health_ready_returns_503_when_database_check_fails(
    client: TestClient,
    monkeypatch,
) -> None:
    async def failing_readiness() -> bool:
        return False

    monkeypatch.setattr(client.app.state.db, "check_readiness", failing_readiness)

    response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"]["status"] == "unavailable"


def test_system_info_returns_expected_contract(client: TestClient) -> None:
    response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "TERRA Core API"
    assert payload["version"]
    assert payload["environment"] == "test"
    assert payload["apiV1Prefix"] == "/api/v1"
    assert payload["authProvider"] == "github"
    assert payload["defaultCrs"] == "EPSG:4326"
    assert payload["githubOauthConfigured"] is False


def test_system_info_reports_github_oauth_configured() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="gh-client-id",
            github_client_secret="gh-client-secret",
        )
    )
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/system/info")

    assert response.status_code == 200
    assert response.json()["githubOauthConfigured"] is True
