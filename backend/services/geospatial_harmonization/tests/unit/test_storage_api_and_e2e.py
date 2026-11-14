"""End-to-end API, service, worker, and S3-compatible integration tests for storage optimization."""

import asyncio
import json
import socket
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from pydantic import SecretStr
from rasterio.transform import from_origin

from geospatial_harmonization.application import HarmonizationService
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, HarmonizationPlan
from geospatial_harmonization.domain.models.storage import StorageReservation
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyJobRepository,
)
from geospatial_harmonization.infrastructure.storage import LocalObjectStore, S3ObjectStore
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository
from geospatial_harmonization.main import create_app
from geospatial_harmonization.storage import (
    ContentDeduplicationService,
    DataCompressionManager,
    StorageLifecycleManager,
    StorageQuotaManager,
    StorageZoneManager,
)
from geospatial_harmonization.worker import WorkerRunner
from geospatial_harmonization.worker.__main__ import build_worker_runtime


def _float64_geotiff_bytes(path: Path, *, width: int = 32, height: int = 32) -> bytes:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=from_origin(0.0, 4.0, 4.0 / width, 4.0 / height),
        nodata=-9999.0,
    ) as dst:
        data = np.full((height, width), 273.123456789, dtype=np.float64)
        dst.write(data, 1)
    return path.read_bytes()


def _wire_full_service_on_app(app: Any, cfg: Settings, transport: MockTransport) -> None:
    handlers = build_default_handler_registry(
        settings=cfg,
        reader_registry=app.state.readers,
        transport=transport,
    )
    app.state.handlers = handlers
    app.state.harmonization_service = HarmonizationService(
        handlers=handlers,
        storage=app.state.storage,
        datasets=app.state.dataset_repo,
        readers=app.state.readers,
        max_grid_pixels=cfg.max_grid_pixels,
        settings=cfg,
        ledger=app.state.ledger,
        zones=app.state.zones,
        quota=app.state.quota,
        dedup=app.state.dedup,
        lifecycle=app.state.lifecycle,
        compression=app.state.compression,
    )


async def test_api_storage_e2e_dedup_compression_monitoring_and_admin_ops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_a = _float64_geotiff_bytes(tmp_path / "src_a.tif", width=64, height=64)
    transport = MockTransport(
        lambda _r: Response(200, content=tif_a, headers={"content-type": "image/tiff"})
    )
    temp_dir = tmp_path / "exec_tmp"
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api_e2e.db'}",
        local_storage_dir=tmp_path / "datalake",
        generic_handler_allowed_hosts=["data.example.org"],
        ghs_storage_budget_bytes=5_000_000,
        ghs_storage_max_object_bytes=2_000_000,
        ghs_storage_max_job_output_bytes=2_000_000,
        ghs_storage_temp_dir=temp_dir,
        ghs_storage_temp_max_bytes=5_000_000,
        ghs_storage_raster_codec="ZSTD",
        ghs_storage_orphan_grace_seconds=1,
        ghs_admin_token=SecretStr("top-secret-admin-token"),
        earthdata_token=SecretStr("top-secret-earthdata-token"),
    )
    app = create_app(cfg)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        _wire_full_service_on_app(app, cfg, transport)

        pol_resp = await client.get("/api/v1/storage/policy")
        assert pol_resp.status_code == 200
        policy_body = pol_resp.json()
        assert policy_body["compression"]["raster_codec"] == "ZSTD"
        assert policy_body["compression"]["allow_lossy_compression"] is False
        assert "top-secret-admin-token" not in json.dumps(policy_body)
        assert "top-secret-earthdata-token" not in json.dumps(policy_body)

        health_ok = await client.get("/api/v1/storage/health")
        assert health_ok.status_code == 200
        assert health_ok.json()["status"] == "ok"

        payload = {
            "provider": "generic",
            "product": "lst_float64",
            "request_payload": {
                "url": "https://data.example.org/scene.tif",
                "product": "lst_float64",
                "data_format": "geotiff",
            },
            "target_grid": {
                "crs": "EPSG:3857",
                "resolution_x": 5000.0,
                "resolution_y": 5000.0,
                "resolution_unit": "meter",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 320000.0, "max_y": 320000.0},
            },
            "variables": ["band_1"],
        }
        res1 = await client.post("/api/v1/harmonize", json=payload)
        assert res1.status_code == 200, res1.text
        body1 = res1.json()
        derived_key_1 = body1["output_assets"][0]["asset_id"]
        assert derived_key_1.startswith("derived/")
        assert body1["dataset"]["variables"]["band_1"]["dtype"] == "float64"

        derived_file = cfg.local_storage_dir / derived_key_1
        with rasterio.open(derived_file) as ds:
            assert ds.compression is not None
            assert ds.compression.name.upper() == "ZSTD"
            assert ds.dtypes == ("float64",)
            arr = ds.read(1)
            assert np.isclose(arr[arr != -9999.0].mean(), 273.123456789, rtol=0, atol=1e-9)

        assert not list(temp_dir.glob("ghs-exec-*"))

        usage_1 = (await client.get("/api/v1/storage/usage")).json()
        assert usage_1["object_count"] == 2
        assert usage_1["zones"]["raw"]["object_count"] == 1
        assert usage_1["zones"]["derived"]["object_count"] == 1
        assert usage_1["reserved_bytes"] == 0
        assert usage_1["compression_savings_bytes"] > 0
        assert usage_1["deduplication_savings_bytes"] == 0

        res2 = await client.post("/api/v1/harmonize", json=payload)
        assert res2.status_code == 200
        usage_2 = (await client.get("/api/v1/storage/usage")).json()
        assert usage_2["zones"]["raw"]["object_count"] == 1
        assert usage_2["deduplication_savings_bytes"] >= len(tif_a)
        assert usage_2["reserved_bytes"] == 0

        assert (await client.post("/api/v1/storage/reconcile")).status_code == 401
        assert (
            await client.post("/api/v1/storage/reconcile", headers={"X-Admin-Token": "wrong-token"})
        ).status_code == 403

        await app.state.storage.put_bytes("intermediate/stray_manual.bin", b"orphan-data")
        rec = await client.post(
            "/api/v1/storage/reconcile",
            headers={"Authorization": "Bearer top-secret-admin-token"},
        )
        assert rec.status_code == 200
        rec_body = rec.json()
        assert "intermediate/stray_manual.bin" in rec_body["untracked_keys"]
        assert rec_body["bytes_difference"] == len(b"orphan-data")

        health_warn = (await client.get("/api/v1/storage/health")).json()
        assert health_warn["status"] == "warning"

        dry_clean = await client.post(
            "/api/v1/storage/cleanup",
            json={"dry_run": True},
            headers={"X-Admin-Token": "top-secret-admin-token"},
        )
        assert dry_clean.status_code == 200
        assert dry_clean.json()["dry_run"] is True


async def test_api_quota_507_object_limit_413_and_unconfigured_admin_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _float64_geotiff_bytes(tmp_path / "src.tif", width=32, height=32)
    transport = MockTransport(
        lambda _r: Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})
    )

    cfg_507 = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'budget_507.db'}",
        local_storage_dir=tmp_path / "store_507",
        generic_handler_allowed_hosts=["data.example.org"],
        ghs_storage_budget_bytes=200,
        ghs_storage_max_object_bytes=500_000,
        ghs_storage_max_job_output_bytes=500_000,
    )
    app_507 = create_app(cfg_507)
    async with (
        app_507.router.lifespan_context(app_507),
        AsyncClient(transport=ASGITransport(app=app_507), base_url="http://test") as client,
    ):
        _wire_full_service_on_app(app_507, cfg_507, transport)
        assert (await client.post("/api/v1/storage/reconcile")).status_code == 503
        assert (await client.post("/api/v1/storage/cleanup")).status_code == 503

        payload = {
            "provider": "generic",
            "product": "ndvi",
            "request_payload": {
                "url": "https://data.example.org/a.tif",
                "product": "ndvi",
                "data_format": "geotiff",
            },
            "target_grid": {
                "crs": "EPSG:3857",
                "resolution_x": 50000.0,
                "resolution_y": 50000.0,
                "resolution_unit": "meter",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 200000.0, "max_y": 200000.0},
            },
            "variables": ["band_1"],
        }
        err_resp = await client.post("/api/v1/harmonize", json=payload)
        assert err_resp.status_code == 507
        body = err_resp.json()
        assert body["error_type"] == "StorageBudgetExceededError"
        assert body["code"] == "STORAGE_BUDGET_EXCEEDED"
        assert body["budget_bytes"] == 200
        assert (await client.get("/api/v1/storage/usage")).json()["reserved_bytes"] == 0

    cfg_413 = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'obj_413.db'}",
        local_storage_dir=tmp_path / "store_413",
        generic_handler_allowed_hosts=["data.example.org"],
        ghs_storage_budget_bytes=1_000_000,
        ghs_storage_max_object_bytes=500,
        ghs_storage_max_job_output_bytes=500,
    )
    app_413 = create_app(cfg_413)
    async with (
        app_413.router.lifespan_context(app_413),
        AsyncClient(transport=ASGITransport(app=app_413), base_url="http://test") as client,
    ):
        _wire_full_service_on_app(app_413, cfg_413, transport)
        resp_413 = await client.post(
            "/api/v1/harmonize",
            json={
                "provider": "generic",
                "product": "ndvi",
                "request_payload": {
                    "url": "https://data.example.org/a.tif",
                    "product": "ndvi",
                    "data_format": "geotiff",
                },
                "variables": ["band_1"],
            },
        )
        assert resp_413.status_code == 413
        body_413 = resp_413.json()
        assert body_413["error_type"] == "ObjectTooLargeError"
        assert body_413["code"] == "OBJECT_TOO_LARGE"


async def test_worker_bounded_concurrency_budget_contention_and_runtime(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker_rt.db'}",
        local_storage_dir=tmp_path / "store",
        ghs_storage_max_worker_concurrency=2,
    )
    rt_engine, rt_runner = await build_worker_runtime(cfg)
    try:
        assert rt_runner.max_concurrency == 2
        await rt_runner.run_maintenance()
    finally:
        await rt_engine.dispose()

    in_flight = 0
    max_observed = 0

    class _CountingService:
        async def execute_plan(self, _plan: Any, *, job_id: Any = None) -> Any:
            nonlocal in_flight, max_observed
            in_flight += 1
            max_observed = max(max_observed, in_flight)
            try:
                await asyncio.sleep(0.05)

                class _FakeDataset:
                    dataset_id = uuid4()

                class _FakeResult:
                    dataset = _FakeDataset()

                return _FakeResult()
            finally:
                in_flight -= 1

    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'conc.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        jobs = SqlAlchemyJobRepository(build_session_factory(engine))
        t0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        for idx in range(5):
            await jobs.create(
                HarmonizationJob(
                    job_id=uuid4(),
                    plan=HarmonizationPlan(
                        plan_id=uuid4(),
                        provider="generic",
                        product=f"p{idx}",
                        request_payload={"url": "https://data.example.org/a.tif"},
                    ),
                    status="pending",
                    created_at=t0,
                    updated_at=t0,
                )
            )
        runner = WorkerRunner(
            service=_CountingService(),  # type: ignore[arg-type]
            jobs=jobs,
            max_concurrency=2,
            poll_interval_seconds=0.02,
        )
        assert await runner.drain() == 5
        assert max_observed == 2
    finally:
        await engine.dispose()


class _ChunkedBody:
    def __init__(self, data: bytes) -> None:
        self._buf = BytesIO(data)

    def read(self, amt: int = 1024) -> bytes:
        return self._buf.read(amt)

    def close(self) -> None:
        self._buf.close()


class _FakeR2Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str, datetime]] = {}
        self.multipart_uploads: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, object]:
        self.objects[(Bucket, Key)] = (Body, ContentType, datetime.now(UTC))
        return {"ETag": '"r2-put"'}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data, content_type, _ = self.objects[(Bucket, Key)]
        return {"Body": _ChunkedBody(data), "ContentType": content_type}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        data, content_type, modified = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(data),
            "ContentType": content_type,
            "LastModified": modified,
            "ETag": '"r2-head"',
        }

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix", ""))
        matching = [
            {"Key": key, "Size": len(data), "LastModified": mod, "ETag": '"r2-list"'}
            for (b, key), (data, _, mod) in sorted(self.objects.items())
            if b == bucket and key.startswith(prefix)
        ]
        return {"Contents": matching, "IsTruncated": False}

    def create_multipart_upload(
        self, *, Bucket: str, Key: str, ContentType: str
    ) -> dict[str, object]:
        self._seq += 1
        uid = f"mp-{self._seq}"
        self.multipart_uploads[uid] = {
            "Bucket": Bucket,
            "Key": Key,
            "ContentType": ContentType,
            "Parts": {},
        }
        return {"UploadId": uid}

    def upload_part(
        self, *, Bucket: str, Key: str, PartNumber: int, UploadId: str, Body: bytes
    ) -> dict[str, object]:
        _ = (Bucket, Key)
        self.multipart_uploads[UploadId]["Parts"][PartNumber] = Body
        return {"ETag": f'"p{PartNumber}"'}

    def complete_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict[str, object]
    ) -> dict[str, object]:
        _ = MultipartUpload
        entry = self.multipart_uploads.pop(UploadId)
        merged = b"".join(entry["Parts"][idx] for idx in sorted(entry["Parts"]))
        self.objects[(Bucket, Key)] = (merged, str(entry["ContentType"]), datetime.now(UTC))
        return {"ETag": '"mp-ok"'}


async def test_s3_r2_backend_harmonization_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _float64_geotiff_bytes(tmp_path / "r2_src.tif", width=16, height=16)
    transport = MockTransport(
        lambda _r: Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})
    )
    cfg = Settings(
        environment="test",
        storage_backend="s3",
        s3_bucket="terra-datalake",
        s3_endpoint_url="https://r2.example.invalid",
        s3_access_key_id=SecretStr("r2-access"),
        s3_secret_access_key=SecretStr("r2-secret"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'r2_e2e.db'}",
        generic_handler_allowed_hosts=["data.example.org"],
        ghs_storage_budget_bytes=2_000_000,
    )
    fake_client = _FakeR2Client()
    s3_store = S3ObjectStore(
        bucket="terra-datalake",
        client=fake_client,
        multipart_threshold_bytes=1024,
    )
    engine = build_async_engine(cfg.database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        sessions = build_session_factory(engine)
        ledger = SqlAlchemyStorageLedgerRepository(sessions)
        await ledger.ensure_ledger_initialized(datetime.now(UTC))
        zones = StorageZoneManager(cfg)
        quota = StorageQuotaManager(ledger, s3_store, cfg)
        dedup = ContentDeduplicationService(s3_store, ledger, zones, cfg)
        lifecycle = StorageLifecycleManager(s3_store, ledger, zones, cfg)
        compression = DataCompressionManager(cfg)

        service = HarmonizationService(
            handlers=build_default_handler_registry(settings=cfg, transport=transport),
            storage=s3_store,
            datasets=SqlAlchemyDatasetRepository(sessions),
            settings=cfg,
            ledger=ledger,
            zones=zones,
            quota=quota,
            dedup=dedup,
            lifecycle=lifecycle,
            compression=compression,
        )
        res = await service.execute_plan(
            HarmonizationPlan(
                plan_id=uuid4(),
                provider="generic",
                product="custom_f64",
                request_payload={
                    "url": "https://data.example.org/r2_scene.tif",
                    "product": "custom_f64",
                    "data_format": "geotiff",
                },
                target_grid=GridSpec(
                    "EPSG:3857",
                    10000.0,
                    10000.0,
                    "meter",
                    SpatialBounds(0.0, 0.0, 160000.0, 160000.0),
                ),
                variables=("band_1",),
            )
        )
        assert res.output_assets[0].uri.startswith("s3://terra-datalake/derived/")
        assert any(k.startswith("raw/") for _, k in fake_client.objects)
        assert any(k.startswith("derived/") for _, k in fake_client.objects)
        reconcile = await quota.reconcile_ledger_with_store(now=datetime.now(UTC))
        assert reconcile.bytes_difference == 0
        assert reconcile.missing_keys == ()
    finally:
        await engine.dispose()


async def test_worker_quota_contention_failure_cleanup_and_maintenance_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _float64_geotiff_bytes(tmp_path / "src_conc.tif", width=16, height=16)

    async def _slow_transport(_request: Any) -> Response:
        await asyncio.sleep(0.05)
        return Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})

    transport = MockTransport(_slow_transport)
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker_conc_e2e.db'}",
        local_storage_dir=tmp_path / "datalake",
        generic_handler_allowed_hosts=["data.example.org"],
        ghs_storage_budget_bytes=100_000,
        ghs_storage_max_object_bytes=95_000,
        ghs_storage_max_job_output_bytes=95_000,
        ghs_storage_max_worker_concurrency=2,
    )
    store = LocalObjectStore(cfg.local_storage_dir)
    engine = build_async_engine(cfg.database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        sessions = build_session_factory(engine)
        ledger = SqlAlchemyStorageLedgerRepository(sessions)
        now = datetime.now(UTC)
        await ledger.ensure_ledger_initialized(now)
        zones = StorageZoneManager(cfg)
        quota = StorageQuotaManager(ledger, store, cfg)
        dedup = ContentDeduplicationService(store, ledger, zones, cfg)
        lifecycle = StorageLifecycleManager(store, ledger, zones, cfg)
        compression = DataCompressionManager(cfg)

        stale_res = StorageReservation(
            reservation_id=uuid4(),
            job_id="stale-crashed-job",
            zone="derived",
            operation="crash_sim",
            reserved_bytes=20_000,
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            status="active",
        )
        await ledger.reserve_capacity(
            stale_res,
            budget_bytes=cfg.ghs_storage_budget_bytes,
            hard_limit_threshold=1.0,
            max_object_bytes=cfg.ghs_storage_max_object_bytes,
            max_job_output_bytes=cfg.ghs_storage_max_job_output_bytes,
            now=now - timedelta(hours=2),
        )

        jobs = SqlAlchemyJobRepository(sessions)
        real_datasets = SqlAlchemyDatasetRepository(sessions)

        class _FailOnceDatasetRepo(SqlAlchemyDatasetRepository):
            def __init__(self, session_factory: Any) -> None:
                super().__init__(session_factory)
                self.fail_next = False

            async def save(self, dataset: Any) -> None:
                if self.fail_next:
                    self.fail_next = False
                    raise RuntimeError("simulated db commit failure")
                await super().save(dataset)

        datasets = _FailOnceDatasetRepo(sessions)
        service = HarmonizationService(
            handlers=build_default_handler_registry(settings=cfg, transport=transport),
            storage=store,
            datasets=datasets,
            settings=cfg,
            ledger=ledger,
            zones=zones,
            quota=quota,
            dedup=dedup,
            lifecycle=lifecycle,
            compression=compression,
        )
        runner = WorkerRunner(
            service=service,
            jobs=jobs,
            max_concurrency=2,
            poll_interval_seconds=0.02,
            quota=quota,
            lifecycle=lifecycle,
        )

        target_grid = GridSpec(
            "EPSG:3857", 10000.0, 10000.0, "meter", SpatialBounds(0.0, 0.0, 160000.0, 160000.0)
        )
        for idx in range(2):
            await jobs.create(
                HarmonizationJob(
                    job_id=uuid4(),
                    plan=HarmonizationPlan(
                        plan_id=uuid4(),
                        provider="generic",
                        product=f"conc_{idx}",
                        request_payload={
                            "url": "https://data.example.org/scene.tif",
                            "product": f"conc_{idx}",
                            "data_format": "geotiff",
                        },
                        target_grid=target_grid,
                        variables=("band_1",),
                    ),
                    status="pending",
                    created_at=now + timedelta(seconds=idx),
                    updated_at=now + timedelta(seconds=idx),
                    max_attempts=1,
                )
            )

        assert await runner.drain() == 2
        reloaded_jobs = await real_datasets.list_recent(limit=10)
        assert len(reloaded_jobs) == 1
        metrics = await ledger.get_usage_metrics(datetime.now(UTC))
        assert metrics.reserved_bytes == 0

        datasets.fail_next = True
        with pytest.raises(RuntimeError, match="simulated db commit failure"):
            await service.execute_plan(
                HarmonizationPlan(
                    plan_id=uuid4(),
                    provider="generic",
                    product="fail_cleanup_prod",
                    request_payload={
                        "url": "https://data.example.org/other_scene.tif",
                        "product": "fail_cleanup_prod",
                        "data_format": "geotiff",
                    },
                    target_grid=GridSpec(
                        "EPSG:3857",
                        20000.0,
                        20000.0,
                        "meter",
                        SpatialBounds(0.0, 0.0, 160000.0, 160000.0),
                    ),
                    variables=("band_1",),
                )
            )
        derived_objs = await store.list_objects("derived/")
        assert len(derived_objs) == 1
        assert (await ledger.get_usage_metrics(datetime.now(UTC))).reserved_bytes == 0

        stop_evt = asyncio.Event()

        async def _stop_soon() -> None:
            await asyncio.sleep(0.05)
            stop_evt.set()

        await asyncio.gather(runner.run_until_stopped(stop_evt), _stop_soon())
    finally:
        await engine.dispose()
