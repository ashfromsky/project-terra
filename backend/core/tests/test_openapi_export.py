"""Tests for deterministic OpenAPI export without a live database."""

import json
from pathlib import Path

from terra.openapi_export import build_openapi_schema, export_openapi_schema


def test_openapi_schema_exposes_all_p0_routes_and_schemas() -> None:
    schema = build_openapi_schema()
    paths = schema["paths"]
    for expected_path in (
        "/health",
        "/health/ready",
        "/api/v1/system/info",
        "/api/v1/auth/github/login",
        "/api/v1/auth/github/callback",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/layers",
        "/api/v1/layers/{layer_id}",
        "/api/v1/layers/{layer_id}/coverage",
        "/api/v1/regions",
        "/api/v1/regions/{region_id}",
        "/api/v1/regions/{region_id}/statistics",
    ):
        assert expected_path in paths

    schemas = schema["components"]["schemas"]
    assert "LayerDefinitionResponse" in schemas
    assert "RegionResponse" in schemas
    assert "GeoJsonPolygonSchema" in schemas
    assert "GeoJsonMultiPolygonSchema" in schemas
    assert "UserResponse" in schemas


def test_export_openapi_schema_writes_valid_json(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "openapi.json"
    written = export_openapi_schema(target)
    assert written == target
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["info"]["title"]
    assert export_openapi_schema(target) == target
