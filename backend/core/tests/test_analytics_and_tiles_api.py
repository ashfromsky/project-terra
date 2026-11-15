"""Tests for analytics and unified tiles endpoints."""

from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terra.modules.analytics.api.router import get_analytics_service
from terra.modules.analytics.application.services import AnalyticsService
from terra.modules.layers.api.router import get_layer_service
from terra.modules.layers.application.services import LayerCatalogService
from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


@pytest.fixture
def mock_ghs_app(client: TestClient) -> FastAPI:
    png_stub = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    geotiff_dataset = {
        "dataset_id": "ds-ndvi-cog-1",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"250m 16 days NDVI": {"name": "250m 16 days NDVI", "units": "dimensionless"}},
        "units": {"250m 16 days NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "geotiff", "storage_key": "cogs/ds-ndvi-cog-1/ndvi.tif"}],
        "extensions": {
            "time_series": {
                "250m 16 days NDVI": {
                    "timestamps": ["2024-06-01T00:00:00Z", "2024-06-17T00:00:00Z"],
                    "values": [0.55, 0.68],
                }
            }
        },
    }

    def handle_ghs(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/datasets":
            return httpx.Response(200, json=[geotiff_dataset])
        if path == "/api/v1/datasets/ds-ndvi-cog-1/tiles/2/1/1.png":
            return httpx.Response(200, content=png_stub, headers={"content-type": "image/png"})
        if path == "/api/v1/datasets/ds-ndvi-cog-1/zonal-statistics":
            return httpx.Response(
                200,
                json={
                    "dataset_id": "ds-ndvi-cog-1",
                    "variable": "250m 16 days NDVI",
                    "timestamp": "2024-06-01",
                    "valid_pixel_count": 1000,
                    "total_pixel_count": 1000,
                    "valid_data_coverage": 1.0,
                    "approx_area_km2": 450.5,
                    "mean": 0.642,
                    "median": 0.651,
                    "min": 0.12,
                    "max": 0.89,
                    "std": 0.082,
                    "q10": 0.52,
                    "q25": 0.59,
                    "q75": 0.71,
                    "q90": 0.78,
                    "histogram": {
                        "bins": [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85],
                        "counts": [10, 25, 45, 120, 300, 350, 120, 30],
                    },
                },
            )
        return httpx.Response(404, json={"detail": "Not found in mock GHS"})

    transport = httpx.MockTransport(handle_ghs)
    app = cast(FastAPI, client.app)

    layer_service = LayerCatalogService(
        StaticLayerCatalogRepository(),
        ghs_base_url="https://mock-ghs.internal",
        ghs_transport=transport,
    )
    analytics_service = AnalyticsService(
        layer_service,
        ghs_base_url="https://mock-ghs.internal",
        ghs_transport=transport,
    )

    app.dependency_overrides[get_layer_service] = lambda: layer_service
    app.dependency_overrides[get_analytics_service] = lambda: analytics_service
    return app


def test_unified_tile_and_tilejson(client: TestClient, mock_ghs_app: FastAPI) -> None:
    # 1. Tile endpoint with alias "ndvi"
    resp = client.get("/api/v1/tiles/ndvi/2024-06-01/2/1/1.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")

    # 2. Tile endpoint with direct layer ID "ndvi-mod13q1"
    resp2 = client.get("/api/v1/tiles/ndvi-mod13q1/2024-06-01/2/1/1.png")
    assert resp2.status_code == 200

    # 3. Invalid zoom
    resp_invalid_z = client.get("/api/v1/tiles/ndvi/2024-06-01/30/1/1.png")
    assert resp_invalid_z.status_code == 422

    # 4. Unknown metric
    resp_unknown = client.get("/api/v1/tiles/unknown-metric/2024-06-01/2/1/1.png")
    assert resp_unknown.status_code == 404

    # 5. TileJSON endpoint
    tj_resp = client.get("/api/v1/tiles/ndvi/2024-06-01/tilejson.json")
    assert tj_resp.status_code == 200
    tj = tj_resp.json()
    assert tj["tilejson"] == "2.2.0"
    assert "tiles" in tj
    assert any("/api/v1/tiles/ndvi/2024-06-01/{z}/{x}/{y}.png" in t for t in tj["tiles"])
    assert tj["minzoom"] == 0
    assert tj["maxzoom"] == 18

    # 6. Layer TileJSON endpoint
    layer_tj = client.get("/api/v1/layers/ndvi-mod13q1/tilejson.json")
    assert layer_tj.status_code == 200
    assert layer_tj.json()["tilejson"] == "2.2.0"


def test_analytics_zonal_statistics(client: TestClient, mock_ghs_app: FastAPI) -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-40.5, -9.5],
                [-39.5, -9.5],
                [-39.5, -8.5],
                [-40.5, -8.5],
                [-40.5, -9.5],
            ]
        ],
    }

    # 1. Valid request with metric alias
    resp = client.post(
        "/api/v1/analytics/zonal-statistics",
        json={
            "metricId": "ndvi",
            "date": "2024-06-01",
            "geometry": geometry,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["metricId"] == "ndvi-mod13q1"
    assert data["date"] == "2024-06-01"
    assert data["mean"] == 0.642
    assert data["median"] == 0.651
    assert data["min"] == 0.12
    assert data["max"] == 0.89
    assert data["std"] == 0.082
    assert data["q10"] == 0.52
    assert data["q90"] == 0.78
    assert data["validPixelCount"] == 1000
    assert data["validDataCoverage"] == 1.0
    assert "histogram" in data
    assert len(data["histogram"]["bins"]) > 0
    assert len(data["histogram"]["counts"]) > 0

    # 2. Time-series POST
    ts_resp = client.post(
        "/api/v1/analytics/zonal-statistics/timeseries",
        json={
            "metricId": "ndvi",
            "geometry": geometry,
        },
    )
    assert ts_resp.status_code == 200
    ts_data = ts_resp.json()
    assert ts_data["metricId"] == "ndvi-mod13q1"
    assert len(ts_data["series"]) >= 1
    assert ts_data["series"][0]["mean"] == 0.642

    # 3. Missing geometry and regionId
    bad_resp = client.post(
        "/api/v1/analytics/zonal-statistics",
        json={"metricId": "ndvi"},
    )
    assert bad_resp.status_code == 422


def test_analytics_zonal_statistics_camel_case_upstream(client: TestClient) -> None:
    """Verify Core parses camelCase fields (validPixelCount, etc.) returned by GHS."""
    geotiff_dataset = {
        "dataset_id": "ds-ndvi-cog-2",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"250m 16 days NDVI": {"name": "250m 16 days NDVI", "units": "dimensionless"}},
        "units": {"250m 16 days NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "geotiff", "storage_key": "cogs/ds-ndvi-cog-2/ndvi.tif"}],
    }

    def handle_ghs(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/datasets":
            return httpx.Response(200, json=[geotiff_dataset])
        if path == "/api/v1/datasets/ds-ndvi-cog-2/zonal-statistics":
            return httpx.Response(
                200,
                json={
                    "datasetId": "ds-ndvi-cog-2",
                    "variableName": "250m 16 days NDVI",
                    "timestamp": "2024-06-01",
                    "validPixelCount": 1234,
                    "totalPixelCount": 2000,
                    "validDataCoverage": 0.617,
                    "approxAreaKm2": 250.25,
                    "mean": 0.75,
                    "median": 0.77,
                    "min": 0.2,
                    "max": 0.95,
                    "std": 0.05,
                    "q10": 0.6,
                    "q25": 0.7,
                    "q75": 0.8,
                    "q90": 0.85,
                    "histogram": {"bins": [0.5, 0.75], "counts": [500, 734]},
                },
            )
        return httpx.Response(404, json={"detail": "Not found in mock GHS"})

    transport = httpx.MockTransport(handle_ghs)
    app = cast(FastAPI, client.app)

    layer_service = LayerCatalogService(
        StaticLayerCatalogRepository(),
        ghs_base_url="https://mock-ghs.internal",
        ghs_transport=transport,
    )
    analytics_service = AnalyticsService(
        layer_service,
        ghs_base_url="https://mock-ghs.internal",
        ghs_transport=transport,
    )

    app.dependency_overrides[get_layer_service] = lambda: layer_service
    app.dependency_overrides[get_analytics_service] = lambda: analytics_service

    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-40.5, -9.5],
                [-39.5, -9.5],
                [-39.5, -8.5],
                [-40.5, -8.5],
                [-40.5, -9.5],
            ]
        ],
    }
    resp = client.post(
        "/api/v1/analytics/zonal-statistics",
        json={"metricId": "ndvi", "date": "2024-06-01", "geometry": geometry},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["validPixelCount"] == 1234
    assert data["totalPixelCount"] == 2000
    assert data["validDataCoverage"] == 0.617
    assert data["approxAreaKm2"] == 250.25
    assert data["mean"] == 0.75
