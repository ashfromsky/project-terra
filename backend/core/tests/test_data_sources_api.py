"""API tests for Core /data-sources discovery, ingestion tracking, and datasets."""

from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.data_sources.api.dependencies import get_ghs_service_client

_AOI_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[24.0, 48.0], [25.0, 48.0], [25.0, 49.0], [24.0, 49.0], [24.0, 48.0]]],
}


class _StubGitHubClient:
    def __init__(self, github_id: int, login: str) -> None:
        self.profile = GitHubProfile(github_id=github_id, github_login=login)

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?client_id=gh&state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


class _StubGhsServiceClient:
    def __init__(self) -> None:
        self.discover_calls: list[dict[str, Any]] = []
        self.submit_calls: list[dict[str, Any]] = []
        self.sync_calls: list[dict[str, Any]] = []
        self.job_status = "pending"
        self.job_dataset_id: str | None = None
        self.datasets: dict[str, dict[str, Any]] = {
            "ds-modis-1": {
                "dataset_id": "ds-modis-1",
                "source_id": "modis_terra_vegetation",
                "provider": "modis",
                "product": "MOD13Q1.061",
                "product_version": "061",
                "granule_id": "batch-mod13",
                "units": {"NDVI": "dimensionless"},
                "variables": {"NDVI": {"name": "NDVI", "units": "dimensionless"}},
                "spatial_metadata": {"crs": "EPSG:4326", "nominal_resolution_m": 250.0},
                "temporal_metadata": {
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-03-01T00:00:00Z",
                    "cadence": "monthly",
                    "semantics": "composite",
                },
                "quality_metadata": {"valid_fraction": 0.94, "qa_policy": "standard"},
                "assets": [],
                "provenance": {"source_provider": "modis"},
                "extensions": {
                    "ingestion_summary": {"observation_count": 3, "warnings": []},
                    "time_series": {
                        "NDVI": {
                            "timestamps": [
                                "2024-01-01T00:00:00Z",
                                "2024-02-01T00:00:00Z",
                                "2024-03-01T00:00:00Z",
                            ],
                            "values": [0.51, 0.56, 0.61],
                        }
                    },
                },
            }
        }

    async def list_providers(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": "modis",
                "title": "MODIS Terra Land",
                "enabled": True,
                "auth_required": True,
                "auth_configured": True,
                "auth_mechanism": "earthdata_token",
                "status": "ready",
                "supports_discovery": True,
                "registered_products": ["MOD13Q1.061"],
                "products": [
                    {
                        "product": "MOD13Q1.061",
                        "version": "061",
                        "title": "Vegetation Indices 16-Day 250m",
                        "spatial_resolution": "250m",
                        "temporal_resolution": "16-day",
                        "crs": "MODIS Sinusoidal",
                        "source_format": "HDF4",
                        "variables": [
                            {
                                "name": "NDVI",
                                "units": "dimensionless",
                                "semantics": "continuous_intensive",
                                "description": "Normalized Difference Vegetation Index",
                            }
                        ],
                    }
                ],
            }
        ]

    async def discover_observations(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.discover_calls.append(payload)
        return {
            "provider": payload["provider"],
            "product": payload["product"],
            "count": 2,
            "observations": [
                {
                    "observation_id": "G1",
                    "provider": payload["provider"],
                    "product": payload["product"],
                    "product_version": "061",
                    "title": "MOD13Q1 Granule 1",
                    "time_start": payload["start_time"],
                    "time_end": payload["end_time"],
                    "bbox": payload["bbox"],
                    "query_mode": "cmr_stac",
                    "access_hint": "earthdata_bearer",
                    "metadata": {},
                }
            ],
        }

    async def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.submit_calls.append(payload)
        return {
            "job_id": "ghs-job-101",
            "status": self.job_status,
            "provider": payload["provider"],
            "product": payload["product"],
            "progress_pct": 0.0,
            "dataset_id": self.job_dataset_id,
            "error_message": None,
            "error_category": None,
        }

    async def run_harmonize_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sync_calls.append(payload)
        ds = dict(self.datasets["ds-modis-1"])
        ds["dataset_id"] = "ds-sync-202"
        self.datasets["ds-sync-202"] = ds
        return {
            "job_id": "ghs-job-sync-202",
            "dataset": ds,
            "quality_report": {},
            "completed_at": "2024-03-01T00:00:00Z",
            "output_assets": [],
            "warnings": [],
        }

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "status": self.job_status,
            "provider": "modis",
            "product": "MOD13Q1.061",
            "progress_pct": 100.0 if self.job_status == "succeeded" else 40.0,
            "dataset_id": self.job_dataset_id,
            "error_message": None,
            "error_category": None,
        }

    async def list_datasets(
        self,
        *,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        items = list(self.datasets.values())
        if provider:
            items = [d for d in items if d["provider"] == provider]
        return items[:limit]

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return self.datasets[dataset_id]


def _oauth_headers(
    client: TestClient,
    github_stub: _StubGitHubClient,
    github_id: int,
    login: str,
) -> dict[str, str]:
    github_stub.profile = GitHubProfile(github_id=github_id, github_login=login)
    auth_url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    cb = client.get("/api/v1/auth/github/callback", params={"code": "ok", "state": state})
    return {"Authorization": f"Bearer {cb.json()['accessToken']}"}


def test_data_sources_discovery_ingestion_polling_and_ownership() -> None:
    stub = _StubGhsServiceClient()
    github_stub = _StubGitHubClient(9001, "other-user")
    app = create_app(
        Settings(
            _env_file=None,
            environment="development",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
        )
    )
    app.dependency_overrides[get_ghs_service_client] = lambda: stub
    app.dependency_overrides[get_github_oauth_client] = lambda: github_stub

    with TestClient(app) as client:
        providers = client.get("/api/v1/data-sources/providers")
        assert providers.status_code == 200
        assert providers.json()[0]["provider"] == "modis"

        assert (
            client.post(
                "/api/v1/data-sources/discover",
                json={
                    "provider": "modis",
                    "product": "MOD13Q1.061",
                    "bbox": [24.0, 48.0, 25.0, 49.0],
                    "startTime": "2024-01-01T00:00:00Z",
                    "endTime": "2024-03-01T00:00:00Z",
                },
            ).status_code
            == 401
        )

        dev_resp = client.post("/api/v1/auth/dev-session")
        assert dev_resp.status_code == 200
        h1 = {"Authorization": f"Bearer {dev_resp.json()['accessToken']}"}

        region = client.post(
            "/api/v1/regions",
            headers=h1,
            json={"name": "Carpathians Test", "role": "primary", "geometry": _AOI_GEOJSON},
        )
        assert region.status_code == 201
        region_id = region.json()["id"]

        discovered = client.post(
            "/api/v1/data-sources/discover",
            headers=h1,
            json={
                "provider": "modis",
                "product": "MOD13Q1.061",
                "regionId": region_id,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-03-01T00:00:00Z",
            },
        )
        assert discovered.status_code == 200
        assert discovered.json()["count"] == 2
        assert stub.discover_calls[0]["bbox"] == [24.0, 48.0, 25.0, 49.0]

        started = client.post(
            "/api/v1/data-sources/ingestions",
            headers=h1,
            json={
                "provider": "modis",
                "product": "MOD13Q1.061",
                "regionId": region_id,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-03-01T00:00:00Z",
                "maxGranules": 12,
                "targetCadence": "monthly",
                "executeNow": False,
            },
        )
        assert started.status_code == 201
        op_id = started.json()["id"]
        assert started.json()["status"] == "pending"
        submitted_payload = stub.submit_calls[0]["request_payload"]
        assert "allow_partial" not in submitted_payload
        assert submitted_payload["data_format"] == "hdf4"
        assert submitted_payload["max_granules"] == 12
        assert stub.submit_calls[0]["target_temporal"]["cadence"] == "monthly"

        stub.job_status = "succeeded"
        stub.job_dataset_id = "ds-modis-1"
        polled = client.get(f"/api/v1/data-sources/ingestions/{op_id}", headers=h1)
        assert polled.status_code == 200
        polled_body = polled.json()
        assert polled_body["status"] == "succeeded"
        assert polled_body["datasetId"] == "ds-modis-1"
        assert polled_body["datasetSummary"]["observationCount"] == 3
        assert polled_body["datasetSummary"]["timeSeriesPreviews"][0]["values"] == [
            0.51,
            0.56,
            0.61,
        ]

        sync_started = client.post(
            "/api/v1/data-sources/ingestions",
            headers=h1,
            json={
                "provider": "gpm_imerg",
                "product": "GPM_3IMERGHH.07",
                "regionId": region_id,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-10T00:00:00Z",
                "targetCadence": "daily",
                "executeNow": True,
            },
        )
        assert sync_started.status_code == 201
        assert sync_started.json()["status"] == "succeeded"
        assert sync_started.json()["datasetId"] == "ds-sync-202"
        assert "allow_partial" not in stub.sync_calls[0]["request_payload"]
        assert stub.sync_calls[0]["target_temporal"]["aggregation"] == "rate_to_depth_sum"

        datasets_list = client.get("/api/v1/data-sources/datasets", headers=h1)
        assert datasets_list.status_code == 200
        ids_by_dataset = {d["datasetId"]: d for d in datasets_list.json()}
        assert ids_by_dataset["ds-modis-1"]["ingestionOperationId"] == op_id
        assert ids_by_dataset["ds-modis-1"]["regionId"] == region_id

        dataset_detail = client.get("/api/v1/data-sources/datasets/ds-modis-1", headers=h1)
        assert dataset_detail.status_code == 200
        assert dataset_detail.json()["validFraction"] == 0.94

        h2 = _oauth_headers(client, github_stub, 9002, "second-user")
        forbidden = client.get(f"/api/v1/data-sources/ingestions/{op_id}", headers=h2)
        assert forbidden.status_code == 403
        u2_datasets = client.get("/api/v1/data-sources/datasets", headers=h2)
        assert u2_datasets.status_code == 200
        assert u2_datasets.json()[0]["ingestionOperationId"] is None
