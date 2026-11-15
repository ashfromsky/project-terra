"""HTTP API tests for ``/api/v1/layers`` endpoints."""

from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from terra.modules.layers.api.router import get_layer_service
from terra.modules.layers.application.services import LayerCatalogService
from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


def test_list_and_filter_layers(client: TestClient) -> None:
    response = client.get("/api/v1/layers")
    assert response.status_code == 200
    layers = response.json()
    assert len(layers) == 16
    assert "shortName" in layers[0]
    assert "availableTimeRange" in layers[0]

    water = client.get("/api/v1/layers", params={"groupId": "water"}).json()
    assert [item["id"] for item in water] == ["precip-gpm-imerg", "soil-moisture-smap"]

    preview = client.get("/api/v1/layers", params={"availabilityStatus": "preview"}).json()
    assert len(preview) == 0
    assert all(
        item["isSyntheticPreview"] is False and item["previewPropertyKey"] is None
        for item in layers
    )


def test_layer_detail_metadata_legend_and_coverage(client: TestClient) -> None:
    detail = client.get("/api/v1/layers/ndvi-mod13q1")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["productId"] == "MOD13Q1"
    assert detail_body["tileSource"]["crs"] == "EPSG:4326"
    assert detail_body["previewPropertyKey"] is None
    assert detail_body["isSyntheticPreview"] is False
    assert detail_body["availabilityStatus"] == "unavailable"
    assert detail_body["unavailableReason"]

    metadata = client.get("/api/v1/layers/lst-mod11a2/metadata")
    assert metadata.status_code == 200
    meta_body = metadata.json()
    assert meta_body["nativeSpatialResolution"] == "1 km"
    assert meta_body["qaPolicy"]
    assert "colorRamp" not in meta_body

    legend = client.get("/api/v1/layers/experimental-tri/legend")
    assert legend.status_code == 200
    legend_body = legend.json()
    assert legend_body["layerId"] == "experimental-tri"
    assert legend_body["valueRange"]["max"] == 100.0
    assert len(legend_body["stops"]) > 0

    today_iso = datetime.now(UTC).date().isoformat()
    expected_end = max("2025-12-31", today_iso)
    expected_steps = (int(expected_end[:4]) - 2001 + 1) * 23

    coverage = client.get("/api/v1/layers/ndvi-mod13q1/coverage")
    assert coverage.status_code == 200
    cov_body = coverage.json()
    assert cov_body == {
        "layerId": "ndvi-mod13q1",
        "startDate": "2001-01-01",
        "endDate": expected_end,
        "cadence": "16-day",
        "totalExpectedSteps": expected_steps,
        "availableSteps": 0,
        "coveragePercent": 0.0,
        "notes": cov_body["notes"],
        "isSimulatedCoverage": False,
        "availableDates": [],
        "datasetBbox": None,
        "activeDatasetId": None,
    }


def test_unknown_layer_returns_404(client: TestClient) -> None:
    for suffix in ("", "/metadata", "/legend", "/coverage"):
        response = client.get(f"/api/v1/layers/does-not-exist{suffix}")
        assert response.status_code == 404


def test_layer_ghs_enrichment_and_raster_proxy_endpoints(client: TestClient) -> None:
    png_stub = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    geotiff_dataset = {
        "dataset_id": "ds-ndvi-cog-1",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "variables": {"NDVI": {"name": "NDVI", "units": "dimensionless"}},
        "units": {"NDVI": "dimensionless"},
        "spatial_metadata": {"crs": "EPSG:4326", "bounds": [-41.0, -10.0, -39.0, -8.0]},
        "assets": [{"data_format": "geotiff", "storage_key": "derived/ndvi.tif"}],
        "extensions": {
            "time_series": {
                "NDVI": {
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
        if path == "/api/v1/datasets/ds-ndvi-cog-1/render.png":
            return httpx.Response(200, content=png_stub, headers={"content-type": "image/png"})
        if path == "/api/v1/datasets/ds-ndvi-cog-1/point":
            return httpx.Response(
                200,
                json={
                    "dataset_id": "ds-ndvi-cog-1",
                    "product": "MOD13Q1.061",
                    "variable": "NDVI",
                    "lon": -40.0,
                    "lat": -9.0,
                    "timestamp": "2024-06-17T00:00:00Z",
                    "status": "ok",
                    "value": 0.68,
                    "raw_value": 6800.0,
                    "unit": "dimensionless",
                    "qa_value": 0,
                    "qa_passed": True,
                    "crs": "EPSG:4326",
                    "nominal_resolution_m": 250.0,
                    "pixel_row": 12,
                    "pixel_col": 8,
                    "bbox": {
                        "min_lon": -41.0,
                        "min_lat": -10.0,
                        "max_lon": -39.0,
                        "max_lat": -8.0,
                    },
                    "time_series": [
                        {"timestamp": "2024-06-01T00:00:00Z", "value": 0.55},
                        {"timestamp": "2024-06-17T00:00:00Z", "value": 0.68},
                    ],
                },
            )
        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(handle_ghs)
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_layer_service] = lambda: LayerCatalogService(
        StaticLayerCatalogRepository(),
        ghs_base_url="http://ghs.test",
        ghs_transport=transport,
    )
    try:
        detail = client.get("/api/v1/layers/ndvi-mod13q1")
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["availabilityStatus"] == "connected"
        assert detail_body["activeDatasetId"] == "ds-ndvi-cog-1"
        assert detail_body["availableDates"] == ["2024-06-01", "2024-06-17"]
        assert detail_body["datasetBbox"] == [-41.0, -10.0, -39.0, -8.0]

        tile = client.get("/api/v1/layers/ndvi-mod13q1/tiles/2/1/1.png")
        assert tile.status_code == 200
        assert tile.headers["content-type"].startswith("image/png")
        assert tile.content == png_stub

        render = client.get(
            "/api/v1/layers/ndvi-mod13q1/render.png",
            params={"bbox": "-41,-10,-39,-8", "width": 64, "height": 64},
        )
        assert render.status_code == 200
        assert render.headers["content-type"].startswith("image/png")
        assert render.content == png_stub

        point_ok = client.get(
            "/api/v1/layers/ndvi-mod13q1/point",
            params={"lon": -40.0, "lat": -9.0},
        )
        assert point_ok.status_code == 200
        ok_body = point_ok.json()
        assert ok_body["status"] == "ok"
        assert ok_body["datasetId"] == "ds-ndvi-cog-1"
        assert ok_body["value"] == pytest.approx(0.68)
        assert ok_body["rawValue"] == pytest.approx(6800.0)
        assert ok_body["qaPassed"] is True
        assert len(ok_body["timeSeries"]) == 2

        point_unavailable = client.get(
            "/api/v1/layers/lst-mod11a2/point",
            params={"lon": -40.0, "lat": -9.0},
        )
        assert point_unavailable.status_code == 200
        unavail_body = point_unavailable.json()
        assert unavail_body["status"] == "unavailable"
        assert unavail_body["value"] is None
        assert unavail_body["reason"]
    finally:
        app.dependency_overrides.clear()
