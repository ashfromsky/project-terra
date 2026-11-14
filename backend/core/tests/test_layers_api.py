"""HTTP API tests for ``/api/v1/layers`` endpoints."""

from fastapi.testclient import TestClient


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
    assert len(preview) == 4
    assert all(item["isSyntheticPreview"] is True for item in preview)


def test_layer_detail_metadata_legend_and_coverage(client: TestClient) -> None:
    detail = client.get("/api/v1/layers/ndvi-mod13q1")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["productId"] == "MOD13Q1"
    assert detail_body["tileSource"]["crs"] == "EPSG:4326"
    assert detail_body["previewPropertyKey"] == "demoNdvi"

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

    coverage = client.get("/api/v1/layers/ndvi-mod13q1/coverage")
    assert coverage.status_code == 200
    cov_body = coverage.json()
    assert cov_body == {
        "layerId": "ndvi-mod13q1",
        "startDate": "2001-01-01",
        "endDate": "2025-12-31",
        "cadence": "16-day",
        "totalExpectedSteps": 575,
        "availableSteps": 0,
        "coveragePercent": 0.0,
        "notes": cov_body["notes"],
        "isSimulatedCoverage": True,
    }


def test_unknown_layer_returns_404(client: TestClient) -> None:
    for suffix in ("", "/metadata", "/legend", "/coverage"):
        response = client.get(f"/api/v1/layers/does-not-exist{suffix}")
        assert response.status_code == 404
