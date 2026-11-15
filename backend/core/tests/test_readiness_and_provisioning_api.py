"""Integration tests for assessment readiness evaluation and adaptive auto-provisioning."""

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.assessments.api.dependencies import get_ghs_dataset_client
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.data_sources.api.dependencies import get_ghs_service_client

_AOI_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[24.0, 48.0], [25.0, 48.0], [25.0, 49.0], [24.0, 49.0], [24.0, 48.0]]],
}


class _StubGitHubClient:
    def __init__(self, github_id: int = 42, login: str = "terra-researcher") -> None:
        self.profile = GitHubProfile(github_id=github_id, github_login=login)

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?client_id=gh&state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


def _login_headers(
    client: TestClient, stub: _StubGitHubClient, gh_id: int, login: str
) -> dict[str, str]:
    stub.profile = GitHubProfile(github_id=gh_id, github_login=login)
    url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get("/api/v1/auth/github/callback", params={"code": "c", "state": state})
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def _power_dataset(dataset_id: str, start_year: int = 2020, end_year: int = 2024) -> dict[str, Any]:
    months = [
        f"{yr:04d}-{mo:02d}-01T00:00:00Z"
        for yr in range(start_year, end_year + 1)
        for mo in range(1, 13)
    ]
    return {
        "dataset_id": dataset_id,
        "source_id": "nasa_power_agroclimatology",
        "provider": "nasa_power",
        "product": "power_daily",
        "product_version": "v2",
        "granule_id": f"power_{start_year}_{end_year}",
        "units": {"PRECTOTCORR": "mm", "T2M": "degC"},
        "variables": {
            "PRECTOTCORR": {
                "name": "PRECTOTCORR",
                "units": "mm",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_extensive",
                "attributes": {"is_scaled": True},
            },
            "T2M": {
                "name": "T2M",
                "units": "degC",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_intensive",
                "attributes": {"is_scaled": True},
            },
        },
        "spatial_metadata": {
            "crs": "EPSG:4326",
            "nominal_resolution_m": 55000.0,
            "bounds": [23.5, 47.5, 25.5, 49.5],
        },
        "temporal_metadata": {
            "start": months[0],
            "end": months[-1],
            "cadence": "monthly",
            "semantics": "interval",
            "aggregation": "none",
        },
        "quality_metadata": {"valid_observation_fraction": 1.0, "qa_policy": "power_valid"},
        "assets": [],
        "provenance": {"retrieval_timestamp": "2025-01-01T00:00:00Z"},
        "extensions": {
            "ingestion_summary": {"observation_count": len(months), "warnings": []},
            "time_series": {
                "PRECTOTCORR": {
                    "timestamps": months,
                    "values": [45.0 + (idx % 12) * 3.0 for idx in range(len(months))],
                    "units": "mm",
                    "is_scaled": True,
                },
                "T2M": {
                    "timestamps": months,
                    "values": [10.0 + (idx % 12) * 1.1 for idx in range(len(months))],
                    "units": "degC",
                    "is_scaled": True,
                },
            },
        },
    }


def _modis_short_dataset(dataset_id: str) -> dict[str, Any]:
    months = [f"2024-{mo:02d}-01T00:00:00Z" for mo in range(1, 7)]
    return {
        "dataset_id": dataset_id,
        "source_id": "modis_terra_vegetation",
        "provider": "modis",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "granule_id": "modis-short-2024",
        "units": {"NDVI": "dimensionless"},
        "variables": {
            "NDVI": {
                "name": "NDVI",
                "units": "dimensionless",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_intensive",
                "valid_range": [-0.2, 1.0],
                "attributes": {"is_scaled": True},
            }
        },
        "spatial_metadata": {
            "crs": "EPSG:4326",
            "nominal_resolution_m": 250.0,
            "bounds": [24.0, 48.0, 25.0, 49.0],
        },
        "temporal_metadata": {
            "start": months[0],
            "end": months[-1],
            "cadence": "monthly",
            "semantics": "interval",
        },
        "quality_metadata": {
            "valid_observation_fraction": 0.92,
            "qa_policy": "modis_pixel_reliability",
            "flags_applied": ["pixel_reliability"],
        },
        "assets": [],
        "provenance": {"retrieval_timestamp": "2025-01-01T00:00:00Z"},
        "extensions": {
            "ingestion_summary": {"observation_count": len(months), "warnings": []},
            "time_series": {
                "NDVI": {
                    "timestamps": months,
                    "values": [0.42, 0.45, 0.51, 0.62, 0.68, 0.70],
                    "units": "dimensionless",
                    "qa_layers": {"pixel_reliability": [0] * 6},
                    "valid_pixel_counts": [100] * 6,
                    "total_pixel_counts": [100] * 6,
                    "is_scaled": True,
                }
            },
        },
    }


class _AdaptiveStubGhsClient:
    def __init__(self, *, modis_auth_configured: bool = False) -> None:
        self.modis_auth_configured = modis_auth_configured
        self.discover_calls: list[dict[str, Any]] = []
        self.sync_calls: list[dict[str, Any]] = []
        self.datasets: dict[str, dict[str, Any]] = {
            "ds-short-modis": _modis_short_dataset("ds-short-modis"),
            "ds-full-power": _power_dataset("ds-full-power", start_year=2020, end_year=2024),
        }

    async def list_providers(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": "nasa_power",
                "title": "NASA POWER Agroclimatology",
                "enabled": True,
                "auth_required": False,
                "auth_configured": True,
                "auth_mechanism": "none",
                "status": "ready",
                "supports_discovery": True,
                "registered_products": ["power_daily"],
                "products": [],
            },
            {
                "provider": "modis",
                "title": "MODIS Terra Land",
                "enabled": True,
                "auth_required": True,
                "auth_configured": self.modis_auth_configured,
                "auth_mechanism": "earthdata_token",
                "status": "ready" if self.modis_auth_configured else "missing_auth",
                "supports_discovery": True,
                "registered_products": ["MOD13Q1.061", "MOD11A2.061"],
                "products": [],
            },
        ]

    async def discover_observations(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.discover_calls.append(payload)
        if payload["provider"] == "nasa_power":
            return {
                "provider": "nasa_power",
                "product": payload["product"],
                "count": 1,
                "observations": [
                    {
                        "observation_id": "power_obs_1",
                        "provider": "nasa_power",
                        "product": payload["product"],
                        "product_version": "v2",
                        "title": "NASA POWER daily",
                    }
                ],
            }
        return {
            "provider": payload["provider"],
            "product": payload["product"],
            "count": 0 if not self.modis_auth_configured else 12,
            "observations": [],
        }

    async def run_harmonize_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sync_calls.append(payload)
        req_payload = payload.get("request_payload") or {}
        start_yr = int(str(req_payload.get("start_time", "2020-01-01"))[:4])
        end_yr = int(str(req_payload.get("end_time", "2024-12-31"))[:4])
        ds_id = "ds-provisioned-power"
        ds = _power_dataset(ds_id, start_year=start_yr, end_year=end_yr)
        self.datasets[ds_id] = ds
        return {
            "job_id": "job-sync-power-1",
            "dataset": ds,
            "quality_report": {},
            "completed_at": "2025-01-01T00:00:00Z",
            "output_assets": [],
            "warnings": [],
        }

    async def submit_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("sync path expected in stub")

    async def get_job(self, job_id: str) -> dict[str, Any]:
        raise AssertionError("sync path expected in stub")

    async def list_datasets(
        self, *, provider: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        items = list(self.datasets.values())
        if provider:
            items = [item for item in items if item["provider"] == provider]
        return items[:limit]

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return self.datasets[dataset_id]

    async def get_dataset_asset_url(
        self, dataset_id: str, *, asset_id: str | None = None, expires_in: int | None = None
    ) -> dict[str, Any]:
        raise AssertionError("unused")

    async def download_dataset_asset_content(
        self, dataset_id: str, *, asset_id: str | None = None
    ) -> tuple[bytes, str, str]:
        raise AssertionError("unused")


def test_assessment_readiness_endpoint_diagnoses_gaps_and_passing_datasets(
    tmp_path: Path,
) -> None:
    ghs_stub = _AdaptiveStubGhsClient()
    gh_stub = _StubGitHubClient()
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'readiness.db'}",
        jwt_secret="test-secret-with-at-least-32-characters-1234",
        scientific_artifact_dir=str(tmp_path / "artifacts"),
    )
    app = create_app(settings)

    def _dataset_client() -> HttpxGhsDatasetClient:
        def dispatch(request: httpx.Request) -> httpx.Response:  # type: ignore[name-defined]
            ds_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=ghs_stub.datasets[ds_id])  # type: ignore[name-defined]

        return HttpxGhsDatasetClient(settings, transport=httpx.MockTransport(dispatch))  # type: ignore[name-defined]

    import httpx

    app.dependency_overrides[get_github_oauth_client] = lambda: gh_stub
    app.dependency_overrides[get_ghs_dataset_client] = _dataset_client
    app.dependency_overrides[get_ghs_service_client] = lambda: ghs_stub

    with TestClient(app) as client:
        headers = _login_headers(client, gh_stub, 42, "terra-researcher")
        # Short 6-month MODIS dataset under strict out_of_sample baseline -> structured gaps
        short_resp = client.post(
            "/api/v1/assessments/readiness",
            headers=headers,
            json={
                "requestConfig": {
                    "request_id": "preview-short",
                    "analysis_start": "2024-01-01T00:00:00Z",
                    "analysis_end": "2024-06-30T00:00:00Z",
                    "target_cadence": "monthly",
                    "baseline": {
                        "baseline_type": "out_of_sample",
                        "min_reference_years": 3,
                        "min_samples_per_period": 3,
                    },
                    "trend": {"min_samples": 12, "use_seasonal_mk": True},
                },
                "ghsDatasetIds": ["ds-short-modis"],
            },
        )
        assert short_resp.status_code == 200, short_resp.text
        short_body = short_resp.json()
        assert short_body["overallStatus"] == "insufficient"
        assert short_body["criteria"]
        assert any(c["status"] == "failed" and c["remediation"] for c in short_body["criteria"])
        assert short_body["suggestedWindowStart"] is not None

        # Multi-year POWER dataset -> ready/partial with passing trend & baseline criteria
        ready_resp = client.post(
            "/api/v1/assessments/readiness",
            headers=headers,
            json={
                "requestConfig": {
                    "request_id": "preview-ready",
                    "analysis_start": "2024-01-01T00:00:00Z",
                    "analysis_end": "2024-12-31T00:00:00Z",
                    "target_cadence": "monthly",
                    "baseline": {
                        "baseline_type": "out_of_sample",
                        "min_reference_years": 3,
                        "min_samples_per_period": 3,
                    },
                    "trend": {"min_samples": 12, "use_seasonal_mk": True},
                },
                "ghsDatasetIds": ["ds-full-power"],
            },
        )
        assert ready_resp.status_code == 200, ready_resp.text
        ready_body = ready_resp.json()
        assert ready_body["overallStatus"] in {"ready", "partial"}
        assert any(
            m["metricId"] == "trend_mann_kendall" and m["status"] == "available"
            for m in ready_body["metrics"]
        )


def test_data_sources_auto_provision_expands_window_reuses_and_reports_fallbacks(
    tmp_path: Path,
) -> None:
    ghs_stub = _AdaptiveStubGhsClient(modis_auth_configured=False)
    # Remove ds-full-power initially so provision actually triggers ingestion for climate
    del ghs_stub.datasets["ds-full-power"]
    gh_stub = _StubGitHubClient()
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'prov.db'}",
        jwt_secret="test-secret-with-at-least-32-characters-1234",
        scientific_artifact_dir=str(tmp_path / "artifacts"),
    )
    app = create_app(settings)

    import httpx

    def _dataset_client() -> HttpxGhsDatasetClient:
        def dispatch(request: httpx.Request) -> httpx.Response:
            ds_id = request.url.path.rsplit("/", 1)[-1]
            if ds_id not in ghs_stub.datasets:
                return httpx.Response(404)
            return httpx.Response(200, json=ghs_stub.datasets[ds_id])

        return HttpxGhsDatasetClient(settings, transport=httpx.MockTransport(dispatch))

    app.dependency_overrides[get_github_oauth_client] = lambda: gh_stub
    app.dependency_overrides[get_ghs_dataset_client] = _dataset_client
    app.dependency_overrides[get_ghs_service_client] = lambda: ghs_stub

    with TestClient(app) as client:
        headers = _login_headers(client, gh_stub, 42, "terra-researcher")
        region_resp = client.post(
            "/api/v1/regions",
            headers=headers,
            json={"name": "Provision Basin", "geometry": _AOI_GEOJSON},
        )
        assert region_resp.status_code == 201
        region_id = region_resp.json()["id"]

        prov_resp = client.post(
            "/api/v1/data-sources/provision",
            headers=headers,
            json={
                "regionId": region_id,
                "analysisStart": "2024-01-01T00:00:00Z",
                "analysisEnd": "2024-12-31T00:00:00Z",
                "targetCadence": "monthly",
                "baselineType": "out_of_sample",
                "minReferenceYears": 3,
                "desiredDomains": ["climate", "vegetation"],
            },
        )
        assert prov_resp.status_code == 200, prov_resp.text
        body = prov_resp.json()
        assert body["windowExpanded"] is True
        assert body["provisionStart"].startswith("2020-") or body["provisionStart"].startswith(
            "2021-"
        )
        assert "ds-provisioned-power" in body["datasetIds"]
        assert any(s["domain"] == "climate" and s["status"] == "ingested" for s in body["steps"])
        assert any(
            s["domain"] == "vegetation" and s["status"] == "unavailable" for s in body["steps"]
        )
        assert body["readiness"] is not None
        assert body["readiness"]["overallStatus"] in {"ready", "partial"}

        # Verify summarize_ghs_dataset populated valid_observation_fraction + qa_layers_present
        ds_resp = client.get("/api/v1/data-sources/datasets/ds-short-modis", headers=headers)
        assert ds_resp.status_code == 200
        ds_body = ds_resp.json()
        assert ds_body["validFraction"] == 0.92
        assert "pixel_reliability" in ds_body["qaLayersPresent"]
        assert ds_body["spanYears"] > 0.3

        # Calling provision again reuses existing climate dataset cleanly
        sync_before = len(ghs_stub.sync_calls)
        reuse_resp = client.post(
            "/api/v1/data-sources/provision",
            headers=headers,
            json={
                "regionId": region_id,
                "analysisStart": "2024-01-01T00:00:00Z",
                "analysisEnd": "2024-12-31T00:00:00Z",
                "targetCadence": "monthly",
                "baselineType": "out_of_sample",
                "minReferenceYears": 3,
                "desiredDomains": ["climate"],
            },
        )
        assert reuse_resp.status_code == 200
        assert len(ghs_stub.sync_calls) == sync_before
        reuse_steps = reuse_resp.json()["steps"]
        assert any(s["domain"] == "climate" and s["status"] == "reused" for s in reuse_steps)

        # Distant AOI bbox must NOT reuse datasets from [24, 48, 25, 49]
        if prov_resp.json()["datasetIds"]:
            ds_id = prov_resp.json()["datasetIds"][0]
            ghs_stub.datasets[ds_id]["spatial_metadata"]["bounds"] = {
                "min_x": 24.0,
                "min_y": 48.0,
                "max_x": 25.0,
                "max_y": 49.0,
            }
        distant_resp = client.post(
            "/api/v1/data-sources/provision",
            headers=headers,
            json={
                "bbox": [12.5, 42.5, 13.0, 43.0],
                "analysisStart": "2024-01-01T00:00:00Z",
                "analysisEnd": "2024-12-31T00:00:00Z",
                "targetCadence": "monthly",
                "baselineType": "out_of_sample",
                "minReferenceYears": 3,
                "desiredDomains": ["climate"],
            },
        )
        assert distant_resp.status_code == 200
        assert len(ghs_stub.sync_calls) > sync_before


def test_build_readiness_request_supports_all_ui_baseline_modes() -> None:
    """Every baseline mode exposed by the UI must produce a valid Scientific Core request."""
    from datetime import UTC, datetime

    from terra.modules.data_sources.application.provisioner import build_readiness_request
    from terra_scientific.domain.enums import BaselineType

    analysis_start = datetime(2024, 1, 1, tzinfo=UTC)
    analysis_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    reference_start = datetime(2022, 1, 1, tzinfo=UTC)
    reference_end = datetime(2023, 12, 31, tzinfo=UTC)

    for mode in ("full_period_explicit", "out_of_sample", "fixed_reference", "cross_validated"):
        request = build_readiness_request(
            analysis_start=analysis_start,
            analysis_end=analysis_end,
            target_cadence="monthly",
            baseline_type=mode,
            reference_start=reference_start,
            reference_end=reference_end,
            min_reference_years=2,
            qa_level="permissive",
        )
        assert request.baseline.baseline_type is BaselineType(mode)
        assert request.baseline.min_years_required == 2
        assert request.baseline.min_samples_per_bin == 2
        if mode == "fixed_reference":
            assert request.baseline.start == reference_start
            assert request.baseline.end == reference_end
        if mode == "full_period_explicit":
            assert request.baseline.allow_explicit_full_period is True
