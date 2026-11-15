"""Tests for Core ObjectStoragePort (local + S3/R2), remote raster fallback, and downloads."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from terra.config import Settings, normalize_s3_endpoint_url
from terra.infrastructure.object_storage import (
    LocalCoreObjectStore,
    S3CoreObjectStore,
    build_core_object_storage,
)
from terra.main import create_app
from terra.modules.assessments.api.dependencies import get_ghs_dataset_client
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.data_sources.api.dependencies import get_ghs_service_client
from terra.modules.data_sources.infrastructure.ghs_service_client import HttpxGhsServiceClient


class _FakeS3Client:
    """In-memory fake mimicking the subset of boto3 S3 API used by S3CoreObjectStore."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        body = bytes(kwargs["Body"])
        self.objects[(bucket, key)] = {
            "Body": body,
            "ContentType": kwargs.get("ContentType", "application/octet-stream"),
            "Metadata": kwargs.get("Metadata", {}),
            "ETag": '"fake-etag-1"',
            "LastModified": datetime.now(UTC),
        }
        return {"ETag": '"fake-etag-1"'}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        rec = self.objects.get((kwargs["Bucket"], kwargs["Key"]))
        if rec is None:
            raise RuntimeError("NoSuchKey")
        return {"Body": io.BytesIO(rec["Body"]), "ContentType": rec["ContentType"]}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_object", kwargs))
        rec = self.objects.get((kwargs["Bucket"], kwargs["Key"]))
        if rec is None:
            err = RuntimeError("NotFound")
            err.response = {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}  # type: ignore[attr-defined]
            raise err
        return {
            "ContentLength": len(rec["Body"]),
            "ContentType": rec["ContentType"],
            "ETag": rec["ETag"],
            "LastModified": rec["LastModified"],
        }

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_object", kwargs))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {}

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_bucket", kwargs))
        return {}

    def generate_presigned_url(
        self,
        client_method: str,
        *,
        Params: dict[str, Any],
        ExpiresIn: int,
    ) -> str:
        self.calls.append(
            ("generate_presigned_url", {"method": client_method, **Params, "ExpiresIn": ExpiresIn})
        )
        return (
            f"https://r2.example.test/{Params['Bucket']}/{Params['Key']}"
            f"?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=fake"
        )


def test_normalize_s3_endpoint_url_strips_bucket_suffix() -> None:
    assert (
        normalize_s3_endpoint_url(
            "https://acc123.r2.cloudflarestorage.com/terra/",
            "terra",
        )
        == "https://acc123.r2.cloudflarestorage.com"
    )
    assert (
        normalize_s3_endpoint_url(
            "https://acc123.r2.cloudflarestorage.com",
            "terra",
        )
        == "https://acc123.r2.cloudflarestorage.com"
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_local_core_object_store_crud_health_and_path_guard(tmp_path: Path) -> None:
    store = LocalCoreObjectStore(tmp_path / "core-objects")
    assert store.backend_name == "local"
    assert await store.check_health() is True

    desc = await store.put_bytes(
        "assessments/abc/result.json",
        b'{"ok": true}',
        content_type="application/json",
    )
    assert desc.key == "assessments/abc/result.json"
    assert desc.size_bytes == 12
    assert desc.checksum_sha256 is not None

    head = await store.head_object("assessments/abc/result.json")
    assert head is not None and head.size_bytes == 12
    assert await store.get_bytes("assessments/abc/result.json") == b'{"ok": true}'
    assert await store.generate_presigned_download_url("assessments/abc/result.json") is None
    assert await store.delete_object("assessments/abc/result.json") is True
    assert await store.head_object("assessments/abc/result.json") is None

    with pytest.raises(ValueError):
        await store.put_bytes("../escape.json", b"nope")


@pytest.mark.anyio
async def test_s3_core_object_store_prefix_presign_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    fake_client = _FakeS3Client()

    def _fake_boto3_client(service_name: str, **kwargs: Any) -> _FakeS3Client:
        captured["service_name"] = service_name
        captured["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(
        "terra.infrastructure.object_storage.store.boto3.client", _fake_boto3_client
    )

    settings = Settings(
        _env_file=None,
        environment="test",
        storage_backend="s3",
        s3_bucket="terra",
        core_s3_prefix="core",
        s3_endpoint_url="https://acc123.r2.cloudflarestorage.com/terra",
        s3_region="auto",
        aws_access_key_id="AKIAFAKEKEY",
        aws_secret_access_key="SECRETFAKEVALUE",
    )
    store = build_core_object_storage(settings)
    assert isinstance(store, S3CoreObjectStore)
    assert store.backend_name == "s3"
    assert captured["service_name"] == "s3"
    assert captured["kwargs"]["endpoint_url"] == "https://acc123.r2.cloudflarestorage.com"
    assert captured["kwargs"]["region_name"] == "auto"
    cfg = captured["kwargs"]["config"]
    assert cfg.signature_version == "s3v4"
    assert cfg.s3["addressing_style"] == "path"

    assert await store.check_health() is True
    desc = await store.put_bytes(
        "assessments/run-1/result.json",
        b'{"status": "completed"}',
        content_type="application/json",
    )
    assert desc.key == "assessments/run-1/result.json"
    assert ("terra", "core/assessments/run-1/result.json") in fake_client.objects
    assert await store.get_bytes(desc.key) == b'{"status": "completed"}'

    presigned = await store.generate_presigned_download_url(
        desc.key,
        expires_in=180,
        filename="result.json",
        content_type="application/json",
    )
    assert presigned is not None
    assert "core/assessments/run-1/result.json" in presigned
    assert "X-Amz-Expires=180" in presigned


def _grid_stack_npz_bytes() -> bytes:
    buf = io.BytesIO()
    timestamps = np.array(
        [f"{yr}-{mo:02d}-01T00:00:00+00:00" for yr in range(2018, 2025) for mo in range(1, 13)]
    )
    data = np.full((len(timestamps), 2, 2), 0.62, dtype=np.float32)
    for idx in range(len(timestamps)):
        data[idx] += np.float32(0.01 * (idx // 12))
    np.savez_compressed(buf, data=data, timestamps=timestamps)
    return buf.getvalue()


def _sample_raster_ghs_dataset() -> dict[str, Any]:
    timestamps = [
        datetime(year, month, 1, tzinfo=UTC).isoformat()
        for year in range(2018, 2025)
        for month in range(1, 13)
    ]
    values = [round(0.55 + 0.01 * (idx // 12), 4) for idx in range(len(timestamps))]
    qa = [0 for _ in timestamps]
    ndvi_meta = {
        "name": "NDVI",
        "canonical_name": "ndvi",
        "units": "dimensionless",
        "semantic_kind": "continuous_intensive",
        "scale_factor": 0.0001,
        "is_scaled": True,
        "fill_values": [-3000.0],
        "valid_range": [-0.2, 1.0],
    }
    evi_meta = {
        **ndvi_meta,
        "name": "EVI",
        "canonical_name": "evi",
    }
    return {
        "dataset_id": "ds-remote-raster-1",
        "source_id": "modis_mod13q1",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "provider": "nasa_earthdata",
        "spatial_metadata": {
            "crs": "EPSG:4326",
            "bounds": [-71.0, 42.0, -70.0, 43.0],
            "nominal_resolution_m": 250.0,
        },
        "temporal_metadata": {
            "cadence": "monthly",
            "semantics": "composite",
            "composite_days": 16,
            "start": timestamps[0],
            "end": timestamps[-1],
        },
        "variables": {"NDVI": ndvi_meta, "EVI": evi_meta},
        "assets": [
            {
                "asset_id": "asset-evi-1",
                "variable": "EVI",
                "storage_key": "derived/ds-remote-raster-1/evi.npz",
            }
        ],
        "extensions": {
            "time_series": {
                "NDVI": {
                    "timestamps": timestamps,
                    "values": values,
                    "qa_layers": {"pixel_reliability": qa},
                    "units": "dimensionless",
                    "is_scaled": True,
                }
            }
        },
    }


class _StubGitHub:
    def __init__(self, profile: GitHubProfile) -> None:
        self.profile = profile

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        _ = code
        return self.profile


def _login_headers(client: TestClient, stub: _StubGitHub, gh_id: int, login: str) -> dict[str, str]:
    stub.profile = GitHubProfile(github_id=gh_id, github_login=login)
    url = client.get("/api/v1/auth/github/login").json()["authorizeUrl"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get("/api/v1/auth/github/callback", params={"code": "c", "state": state})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['accessToken']}"}


def test_assessment_artifact_persistence_download_and_authz(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_s3 = _FakeS3Client()
    monkeypatch.setattr(
        "terra.infrastructure.object_storage.store.boto3.client", lambda *a, **k: fake_s3
    )

    db_file = tmp_path / "core.db"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        scientific_artifact_dir=str(tmp_path / "artifacts"),
        storage_backend="s3",
        s3_bucket="terra",
        core_s3_prefix="core",
        s3_endpoint_url="https://acc123.r2.cloudflarestorage.com",
        aws_access_key_id="AKIAFAKE",
        aws_secret_access_key="SECRETFAKE",
        jwt_secret_key="test-jwt-secret-key-at-least-32-chars",
        ghs_base_url="http://ghs.test",
    )

    npz_payload = _grid_stack_npz_bytes()
    dataset_payload = _sample_raster_ghs_dataset()
    fetched_asset_paths: list[str] = []

    def _mock_ghs(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/datasets/ds-remote-raster-1":
            return httpx.Response(200, json=dataset_payload)
        if request.url.path == "/api/v1/datasets/ds-remote-raster-1/asset-content":
            fetched_asset_paths.append(request.url.path)
            return httpx.Response(
                200,
                content=npz_payload,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": 'attachment; filename="ndvi.npz"',
                },
            )
        if request.url.path == "/api/v1/datasets/ds-remote-raster-1/asset-url":
            return httpx.Response(
                200,
                json={
                    "dataset_id": "ds-remote-raster-1",
                    "asset_id": "asset-1",
                    "storage_key": "derived/ds-remote-raster-1/ndvi.npz",
                    "filename": "ndvi.npz",
                    "media_type": "application/octet-stream",
                    "size_bytes": len(npz_payload),
                    "checksum_sha256": "abc123",
                    "download_url": "https://r2.example.test/terra/derived/ds-remote-raster-1/ndvi.npz?X-Amz-Signature=ok",
                    "presigned": True,
                    "expires_in": 300,
                },
            )
        if request.url.path == "/api/v1/datasets/derived":
            return httpx.Response(201, json={"dataset_id": "derived-out-1"})
        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(_mock_ghs)
    stub_gh = _StubGitHub(GitHubProfile(github_id=101, github_login="owner_r2"))
    app = create_app(settings)
    app.dependency_overrides[get_github_oauth_client] = lambda: stub_gh
    app.dependency_overrides[get_ghs_dataset_client] = lambda: HttpxGhsDatasetClient(
        settings, transport=transport
    )

    class _PatchedServiceClient(HttpxGhsServiceClient):
        async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:  # type: ignore[override]
            async with httpx.AsyncClient(base_url="http://ghs.test", transport=transport) as client:
                resp = await client.request(method, path, params=kwargs.get("params"))
            return resp.json()

        async def download_dataset_asset_content(
            self, dataset_id: str, *, asset_id: str | None = None
        ) -> tuple[bytes, str, str]:
            _ = (dataset_id, asset_id)
            return npz_payload, "application/octet-stream", "ndvi.npz"

    app.dependency_overrides[get_ghs_service_client] = lambda: _PatchedServiceClient(
        "http://ghs.test"
    )

    with TestClient(app) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {
            "database": {"status": "ok"},
            "object_storage": {"status": "ok"},
        }
        sys_info = client.get("/api/v1/system/info")
        assert sys_info.status_code == 200
        assert sys_info.json()["storageBackend"] == "s3"

        headers_owner = _login_headers(client, stub_gh, 101, "owner_r2")
        headers_other = _login_headers(client, stub_gh, 202, "other_r2")

        created = client.post(
            "/api/v1/assessments",
            headers=headers_owner,
            json={
                "title": "R2 Assessment Run",
                "executeNow": True,
                "ghsDatasetIds": ["ds-remote-raster-1"],
                "requestConfig": {
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
            },
        )
        assert created.status_code == 201
        body = created.json()
        assessment_id = UUID(body["id"])
        assert body["status"] in {"completed", "insufficient_data"}
        assert fetched_asset_paths == ["/api/v1/datasets/ds-remote-raster-1/asset-content"]
        assert body["artifactPaths"]["object_storage_backend"] == "s3"
        assert (
            body["artifactPaths"]["result_object_key"] == f"assessments/{assessment_id}/result.json"
        )
        assert (
            body["artifactPaths"]["provenance_object_key"]
            == f"assessments/{assessment_id}/provenance.json"
        )
        assert ("terra", f"core/assessments/{assessment_id}/result.json") in fake_s3.objects
        assert ("terra", f"core/assessments/{assessment_id}/provenance.json") in fake_s3.objects
        assert Path(body["artifactPaths"]["assessment_result_json"]).exists()

        # Verify listing returns presigned R2 URLs for both result.json and provenance.json
        listed = client.get(f"/api/v1/assessments/{assessment_id}/artifacts", headers=headers_owner)
        assert listed.status_code == 200
        items = listed.json()
        assert [item["name"] for item in items] == ["result.json", "provenance.json"]
        assert all(
            item["presigned"] is True and "r2.example.test" in item["presignedUrl"]
            for item in items
        )

        # Verify direct Core download streams exact JSON payload
        dl_res = client.get(
            f"/api/v1/assessments/{assessment_id}/artifacts/provenance.json",
            headers=headers_owner,
        )
        assert dl_res.status_code == 200
        prov_json = json.loads(dl_res.content.decode("utf-8"))
        assert prov_json["assessment_id"] == str(assessment_id)
        assert prov_json["ghs_dataset_ids"] == ["ds-remote-raster-1"]

        # Verify cross-user isolation
        forbidden = client.get(
            f"/api/v1/assessments/{assessment_id}/artifacts",
            headers=headers_other,
        )
        assert forbidden.status_code == 403

        # Verify DataSources presigned download URL and proxy download
        ds_url = client.get(
            "/api/v1/data-sources/datasets/ds-remote-raster-1/download-url",
            headers=headers_owner,
        )
        assert ds_url.status_code == 200
        assert ds_url.json()["presigned"] is True
        assert "r2.example.test" in ds_url.json()["downloadUrl"]

        ds_dl = client.get(
            "/api/v1/data-sources/datasets/ds-remote-raster-1/download",
            headers=headers_owner,
        )
        assert ds_dl.status_code == 200
        assert ds_dl.content == npz_payload
