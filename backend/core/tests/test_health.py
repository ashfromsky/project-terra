"""Tests for the health endpoints."""

from fastapi.testclient import TestClient


def test_root_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"]
    assert payload["version"]


def test_v1_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_openapi_document_lists_health_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
    assert "/api/v1/health" in schema["paths"]


def test_cors_headers_absent_without_origins(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_headers_present_with_configured_origins(cors_client: TestClient) -> None:
    response = cors_client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
