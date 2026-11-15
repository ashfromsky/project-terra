"""API, domain validation, GIBS rejection, and ownership tests for Assessments endpoints."""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.assessments.api.dependencies import get_ghs_dataset_client
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile

_BOX = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


class _StubGitHub:
    def __init__(self, profile: GitHubProfile) -> None:
        self.profile = profile

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


def _login_headers(client: TestClient, stub: _StubGitHub, gh_id: int, login: str) -> dict[str, str]:
    stub.profile = GitHubProfile(github_id=gh_id, github_login=login)
    url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get("/api/v1/auth/github/callback", params={"code": "c", "state": state})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def _sample_mod13_dataset_dict() -> dict[str, object]:
    timestamps = [
        datetime(year, month, 1, tzinfo=UTC).isoformat()
        for year in range(2018, 2025)
        for month in range(1, 13)
    ]
    values = [round(0.55 + 0.01 * (idx // 12), 4) for idx in range(len(timestamps))]
    qa = [0 for _ in timestamps]
    meta = {
        "name": "NDVI",
        "canonical_name": "ndvi",
        "units": "dimensionless",
        "semantic_kind": "continuous_intensive",
        "scale_factor": 0.0001,
        "is_scaled": True,
        "fill_values": [-3000.0],
        "valid_range": [-0.2, 1.0],
    }
    return {
        "dataset_id": "mod13-sample",
        "source_id": "modis_mod13q1",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "provider": "nasa_earthdata",
        "spatial_support": {"crs": "EPSG:4326", "nominal_resolution_m": 250.0},
        "temporal_metadata": {
            "cadence": "monthly",
            "semantics": "composite",
            "composite_days": 16,
            "start": timestamps[0],
            "end": timestamps[-1],
        },
        "variables": {"NDVI": meta},
        "series": {
            "NDVI": {
                "timestamps": timestamps,
                "values": values,
                "qa_layers": {"pixel_reliability": qa},
                "metadata": meta,
            }
        },
    }


def test_assessments_require_auth_while_method_catalog_is_readable(client: TestClient) -> None:
    assert client.get("/api/v1/assessments").status_code == 401
    methods_resp = client.get("/api/v1/assessments/methods")
    assert methods_resp.status_code == 200
    methods = methods_resp.json()
    assert any(m["methodId"] == "mann_kendall" and m["implemented"] is True for m in methods)
    assert any(m["methodId"] == "composite_tri" and m["implemented"] is False for m in methods)


def test_assessment_lifecycle_execution_ownership_and_gibs_rejection() -> None:
    stub = _StubGitHub(GitHubProfile(github_id=1, github_login="user1"))
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            ghs_timeout_seconds=0.01,
        )
    )
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        h1 = _login_headers(client, stub, 2001, "sci_owner")
        h2 = _login_headers(client, stub, 2002, "other_user")

        region = client.post(
            "/api/v1/regions",
            headers=h1,
            json={"name": "Carpathians", "role": "primary", "geometry": _BOX},
        ).json()

        payload = {
            "title": "Carpathian NDVI Assessment",
            "regionId": region["id"],
            "executeNow": True,
            "requestConfig": {
                "request_id": "api-req-1",
                "analysis_start": "2021-01-01T00:00:00Z",
                "analysis_end": "2024-12-31T00:00:00Z",
                "target_cadence": "monthly",
                "baseline": {
                    "baseline_type": "fixed_reference",
                    "start": "2018-01-01T00:00:00Z",
                    "end": "2020-12-31T00:00:00Z",
                    "min_years_required": 3,
                    "min_samples_per_bin": 3,
                },
            },
            "inlineDatasets": [_sample_mod13_dataset_dict()],
        }
        created = client.post("/api/v1/assessments", headers=h1, json=payload)
        assert created.status_code == 201
        detail = created.json()
        assert detail["status"] == "completed"
        assert detail["result"]["trends"][0]["direction"] == "increasing"
        assert detail["result"]["resilience"][0]["composite_tri"]["status"] == (
            "unavailable_unvalidated"
        )

        assessment_id = detail["id"]
        assert client.get(f"/api/v1/assessments/{assessment_id}", headers=h1).status_code == 200
        assert client.get(f"/api/v1/assessments/{assessment_id}", headers=h2).status_code == 403

        # Queued execution path via explicit POST /execute
        queued_payload = {**payload, "title": "Queued Assessment", "executeNow": False}
        queued = client.post("/api/v1/assessments", headers=h1, json=queued_payload)
        assert queued.status_code == 201
        assert queued.json()["status"] == "queued"

        executed = client.post(
            f"/api/v1/assessments/{queued.json()['id']}/execute",
            headers=h1,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "completed"

        # GIBS quantitative ingestion must be rejected cleanly with 422
        gibs_ds = _sample_mod13_dataset_dict()
        gibs_ds["source_id"] = "nasa_gibs"
        gibs_ds["provider"] = "nasa_gibs"
        gibs_payload = {**payload, "title": "Invalid GIBS", "inlineDatasets": [gibs_ds]}
        gibs_resp = client.post("/api/v1/assessments", headers=h1, json=gibs_payload)
        assert gibs_resp.status_code == 422

        listed = client.get("/api/v1/assessments", headers=h1)
        assert listed.status_code == 200
        assert len(listed.json()) == 2
        assert len(client.get("/api/v1/assessments", headers=h2).json()) == 0


def test_assessment_ghs_client_mapping_artifacts_and_openapi(tmp_path: Path) -> None:
    timestamps = [
        datetime(year, month, 1, tzinfo=UTC).isoformat()
        for year in range(2018, 2025)
        for month in range(1, 13)
    ]
    ndvi_vals = [round(0.50 + 0.012 * (idx // 12), 4) for idx in range(len(timestamps))]
    qa_vals = [0 for _ in timestamps]

    published_products: list[str] = []

    def _ghs_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/datasets/derived":
            import json as _json

            payload = _json.loads(request.content.decode("utf-8"))
            product = str(payload["product"])
            published_products.append(product)
            return httpx.Response(201, json={"dataset_id": f"derived-{product.lower()}"})
        if request.url.path == "/api/v1/datasets/ghs-mod13-1":
            return httpx.Response(
                200,
                json={
                    "dataset_id": "ghs-mod13-1",
                    "product": "MOD13Q1.061",
                    "product_version": "061",
                    "provider": "nasa_earthdata",
                    "granule_id": "MOD13Q1.A2018001.h19v04.061",
                    "spatial_metadata": {
                        "crs": "EPSG:4326",
                        "bounds": [23.0, 48.0, 25.0, 49.5],
                        "nominal_resolution_m": 250.0,
                    },
                    "temporal": {
                        "cadence": "monthly",
                        "semantics": "composite",
                        "composite_days": 16,
                        "start": timestamps[0],
                        "end": timestamps[-1],
                    },
                    "variables": {
                        "NDVI": {
                            "units": "dimensionless",
                            "semantic_kind": "continuous_intensive",
                            "scale_factor": 0.0001,
                            "is_scaled": True,
                            "fill_values": [-3000.0],
                            "valid_range": [-0.2, 1.0],
                        }
                    },
                    "provenance": {"retrieval_timestamp": "2026-01-01T00:00:00Z"},
                    "extensions": {
                        "time_series": {
                            "NDVI": {
                                "timestamps": timestamps,
                                "values": ndvi_vals,
                                "qa_layers": {"pixel_reliability": qa_vals},
                            }
                        }
                    },
                },
            )
        return httpx.Response(404, json={"detail": "Not found"})

    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ghs_base_url="http://ghs.test",
        scientific_artifact_dir=str(tmp_path),
    )
    stub = _StubGitHub(GitHubProfile(github_id=3001, github_login="ghs_user"))
    app = create_app(settings)
    app.dependency_overrides[get_github_oauth_client] = lambda: stub
    app.dependency_overrides[get_ghs_dataset_client] = lambda: HttpxGhsDatasetClient(
        settings, transport=httpx.MockTransport(_ghs_handler)
    )

    spec_paths = app.openapi()["paths"]
    for expected_path in (
        "/api/v1/assessments/methods",
        "/api/v1/assessments",
        "/api/v1/assessments/{assessment_id}",
        "/api/v1/assessments/{assessment_id}/execute",
    ):
        assert expected_path in spec_paths

    with TestClient(app) as client:
        headers = _login_headers(client, stub, 3001, "ghs_user")
        base_req = {
            "request_id": "ghs-req-1",
            "analysis_start": "2021-01-01T00:00:00Z",
            "analysis_end": "2024-12-31T00:00:00Z",
            "target_cadence": "monthly",
            "baseline": {
                "baseline_type": "fixed_reference",
                "start": "2018-01-01T00:00:00Z",
                "end": "2020-12-31T00:00:00Z",
                "min_years_required": 3,
                "min_samples_per_bin": 3,
            },
        }
        created = client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "title": "GHS Linked Assessment",
                "executeNow": True,
                "requestConfig": base_req,
                "ghsDatasetIds": ["ghs-mod13-1"],
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "completed"
        assert body["artifactPaths"]
        assert Path(body["artifactPaths"]["assessment_result_json"]).exists()
        assert body["artifactPaths"]["assessment_result_sha256"]
        assert "TERRA-NDVI-ANOM" in published_products
        assert "TERRA-VEG-TREND" in published_products
        assert "TERRA-MK-TEST" in published_products
        assert "TERRA-SEN-SLOPE" in published_products
        assert "TERRA-TRI" not in published_products
        assert body["artifactPaths"]["ghs_derived:TERRA-NDVI-ANOM"] == "derived-terra-ndvi-anom"

        # Map-driven runs can opt out of derived raster publication without changing the
        # scientific result payload.
        published_products.clear()
        minimal = client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "title": "GHS Linked Assessment Without Derived Rasters",
                "executeNow": True,
                "requestConfig": {
                    **base_req,
                    "request_id": "ghs-req-2",
                    "publish_derived_spatial_artifacts": False,
                },
                "ghsDatasetIds": ["ghs-mod13-1"],
            },
        )
        assert minimal.status_code == 201
        minimal_body = minimal.json()
        assert minimal_body["status"] == "completed"
        assert minimal_body["result"]["status"] == "completed"
        assert published_products == []
        assert "assessment_result_json" in minimal_body["artifactPaths"]

        # Unsafe output_artifact_dir outside configured root must fail 422
        escape = client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "title": "Unsafe Artifact Path",
                "executeNow": False,
                "requestConfig": {**base_req, "output_artifact_dir": "/tmp/outside-terra"},
                "ghsDatasetIds": ["ghs-mod13-1"],
            },
        )
        assert escape.status_code == 422

        # Missing GHS dataset maps to 502 Bad Gateway
        missing = client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "title": "Missing GHS Dataset",
                "executeNow": True,
                "requestConfig": base_req,
                "ghsDatasetIds": ["does-not-exist"],
            },
        )
        assert missing.status_code == 502

        # Traversal dataset ID maps to 502 Bad Gateway before request
        traversal = client.post(
            "/api/v1/assessments",
            headers=headers,
            json={
                "title": "Traversal GHS Dataset",
                "executeNow": True,
                "requestConfig": base_req,
                "ghsDatasetIds": ["../etc/passwd"],
            },
        )
        assert traversal.status_code == 502
