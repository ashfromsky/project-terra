"""End-to-end tests for HarmonizationService and WorkerRunner."""

import asyncio
import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from httpx import MockTransport, Request, Response
from rasterio.transform import from_origin

from geospatial_harmonization.application import HarmonizationService
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, HarmonizationPlan
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
from geospatial_harmonization.infrastructure.storage import LocalObjectStore
from geospatial_harmonization.worker import WorkerRunner


def _make_geotiff_bytes(path: Path) -> bytes:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0, 4.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((4, 4), 0.75, dtype=np.float32), 1)
    return path.read_bytes()


async def test_worker_end_to_end_generic_geotiff_and_nasa_power(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _make_geotiff_bytes(tmp_path / "src.tif")
    power_json = json.dumps(
        {
            "geometry": {"coordinates": [30.5, 50.4, 150.0]},
            "properties": {"parameter": {"T2M": {"20260701": 22.5, "20260702": 24.5}}},
        }
    ).encode("utf-8")

    def http_dispatch(request: Request) -> Response:
        if "power.larc.nasa.gov" in request.url.host:
            return Response(200, content=power_json, headers={"content-type": "application/json"})
        return Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})

    transport = MockTransport(http_dispatch)
    handlers = build_default_handler_registry(
        settings=Settings(generic_handler_allowed_hosts=["data.example.org"]),
        raw_dir=tmp_path / "handler_raw",
        transport=transport,
    )
    storage = LocalObjectStore(tmp_path / "storage")
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        sessions = build_session_factory(engine)
        datasets = SqlAlchemyDatasetRepository(sessions)
        jobs = SqlAlchemyJobRepository(sessions)
        service = HarmonizationService(handlers=handlers, storage=storage, datasets=datasets)
        runner = WorkerRunner(service=service, jobs=jobs, poll_interval_seconds=0.05)

        target_grid = GridSpec(
            "EPSG:3857", 50000.0, 50000.0, "meter", SpatialBounds(0.0, 0.0, 200000.0, 200000.0)
        )
        t0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        job1 = HarmonizationJob(
            job_id=uuid4(),
            plan=HarmonizationPlan(
                plan_id=uuid4(),
                provider="generic",
                product="custom_tif",
                request_payload={
                    "url": "https://data.example.org/ndvi.tif",
                    "product": "custom_tif",
                    "data_format": "geotiff",
                },
                target_grid=target_grid,
                variables=("band_1",),
            ),
            status="pending",
            created_at=t0,
            updated_at=t0,
        )
        job2 = HarmonizationJob(
            job_id=uuid4(),
            plan=HarmonizationPlan(
                plan_id=uuid4(),
                provider="nasa_power",
                product="nasa_power",
                request_payload={
                    "parameters": ["T2M"],
                    "latitude": 50.4,
                    "longitude": 30.5,
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                },
            ),
            status="pending",
            created_at=t0,
            updated_at=t0,
        )
        await jobs.create(job1)
        await jobs.create(job2)

        assert await runner.drain() == 2
        done1 = await jobs.get_by_id(job1.job_id)
        done2 = await jobs.get_by_id(job2.job_id)
        assert done1 is not None and done1.status == "succeeded" and done1.dataset_id is not None
        assert done2 is not None and done2.status == "succeeded" and done2.dataset_id is not None

        ds1 = await datasets.get_by_id(done1.dataset_id)
        assert ds1 is not None and await storage.exists(ds1.assets[0].asset_id)

        bad_job = HarmonizationJob(
            job_id=uuid4(),
            plan=HarmonizationPlan(
                plan_id=uuid4(),
                provider="unknown_provider",
                product="bad",
                request_payload={},
            ),
            status="pending",
            created_at=t0,
            updated_at=t0,
            max_attempts=1,
        )
        await jobs.create(bad_job)
        assert await runner.run_once() is True
        failed = await jobs.get_by_id(bad_job.job_id)
        assert failed is not None and failed.status == "failed"
        assert (
            failed.error_message is not None and "IncompatibleDatasetError" in failed.error_message
        )

        stop = asyncio.Event()
        stop.set()
        await runner.run_until_stopped(stop)
    finally:
        await engine.dispose()


async def test_worker_retry_backoff_fail_fast_isolation_and_cancellation(tmp_path: Path) -> None:
    from datetime import timedelta

    import httpx

    from geospatial_harmonization.domain.models.harmonization import HarmonizationJob
    from geospatial_harmonization.handlers import HandlerRegistry
    from geospatial_harmonization.handlers.modis import MODISHandler
    from geospatial_harmonization.handlers.nasa_power import NASAPowerHandler
    from geospatial_harmonization.infrastructure.storage import build_storage_port
    from geospatial_harmonization.infrastructure.storage_ledger import (
        SqlAlchemyStorageLedgerRepository,
    )
    from geospatial_harmonization.readers import build_default_reader_registry
    from geospatial_harmonization.storage.dedup import ContentDeduplicationService
    from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
    from geospatial_harmonization.storage.quota import StorageQuotaManager
    from geospatial_harmonization.storage.zones import StorageZoneManager

    cfg = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker_retry.db'}",
        local_storage_dir=tmp_path / "store",
        nasa_power_enabled=True,
        modis_enabled=True,
        http_max_retries=1,
        http_retry_backoff_seconds=0.0,
    )
    engine = build_async_engine(cfg.database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        sessions = build_session_factory(engine)
        datasets = SqlAlchemyDatasetRepository(sessions)
        jobs = SqlAlchemyJobRepository(sessions)
        ledger = SqlAlchemyStorageLedgerRepository(sessions)
        t0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        await ledger.ensure_ledger_initialized(t0)
        storage = build_storage_port(cfg)
        zones = StorageZoneManager(cfg)
        quota = StorageQuotaManager(ledger, storage, cfg)
        dedup = ContentDeduplicationService(storage, ledger, zones, cfg)
        lifecycle = StorageLifecycleManager(storage, ledger, zones, cfg)

        readers = build_default_reader_registry()
        sample_power = {
            "properties": {"parameter": {"PRECTOTCORR": {"20260701": 4.2, "20260702": 0.0}}},
            "geometry": {"coordinates": [30.0, 50.0, 120.0]},
            "parameters": {"PRECTOTCORR": {"units": "mm/day", "longname": "Precipitation"}},
            "header": {"fill_value": -999.0},
        }
        calls = {"transient": 0}

        def _power_responder(_request: httpx.Request) -> httpx.Response:
            calls["transient"] += 1
            if calls["transient"] <= 2:
                return httpx.Response(503, text="Upstream busy")
            return httpx.Response(200, json=sample_power)

        def _auth_fail_responder(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        reg = HandlerRegistry()
        reg.register(
            NASAPowerHandler(
                settings=cfg,
                transport=httpx.MockTransport(_power_responder),
            )
        )
        reg.register(
            MODISHandler(
                settings=cfg,
                reader_registry=readers,
                transport=httpx.MockTransport(_auth_fail_responder),
            )
        )

        service = HarmonizationService(
            handlers=reg,
            storage=storage,
            datasets=datasets,
            readers=readers,
            settings=cfg,
            ledger=ledger,
            zones=zones,
            quota=quota,
            dedup=dedup,
            lifecycle=lifecycle,
        )
        now_box = [t0]
        runner = WorkerRunner(
            service=service,
            jobs=jobs,
            retry_backoff_seconds=10.0,
            quota=quota,
            lifecycle=lifecycle,
            clock=lambda: now_box[0],
        )

        auth_job = HarmonizationJob(
            job_id=uuid4(),
            plan=HarmonizationPlan(
                plan_id=uuid4(),
                provider="modis",
                product="MOD13Q1.061",
                request_payload={
                    "product": "MOD13Q1.061",
                    "start_time": "2026-07-01T00:00:00Z",
                    "bbox": [30.0, 50.0, 31.0, 51.0],
                },
            ),
            status="pending",
            created_at=t0,
            updated_at=t0,
            max_attempts=3,
        )
        power_plan_a = HarmonizationPlan(
            plan_id=uuid4(),
            provider="nasa_power",
            product="power_daily",
            request_payload={
                "product": "power_daily",
                "mode": "point",
                "latitude": 50.0,
                "longitude": 30.0,
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "parameters": ["PRECTOTCORR"],
            },
        )
        power_plan_b = HarmonizationPlan(
            plan_id=uuid4(),
            provider="nasa_power",
            product="power_daily",
            request_payload=power_plan_a.request_payload,
        )
        assert power_plan_a.compute_idempotency_key() == power_plan_b.compute_idempotency_key()

        power_job = HarmonizationJob(
            job_id=uuid4(),
            plan=power_plan_a,
            status="pending",
            created_at=t0 + timedelta(seconds=1),
            updated_at=t0 + timedelta(seconds=1),
            max_attempts=3,
            idempotency_key=power_plan_a.compute_idempotency_key(),
        )
        await jobs.create(auth_job)
        await jobs.create(power_job)

        assert await runner.run_once() is True
        auth_state = await jobs.get_by_id(auth_job.job_id)
        assert auth_state is not None
        assert auth_state.status == "failed"
        assert auth_state.attempt == 1
        assert auth_state.error_category == "authentication"

        assert await runner.run_once() is True
        transient_state = await jobs.get_by_id(power_job.job_id)
        assert transient_state is not None
        assert transient_state.status == "pending"
        assert transient_state.error_category == "network"
        assert transient_state.next_retry_at == t0 + timedelta(seconds=10)

        now_box[0] = t0 + timedelta(seconds=5)
        assert await runner.run_once() is False

        now_box[0] = t0 + timedelta(seconds=11)
        assert await runner.run_once() is True
        succeeded = await jobs.get_by_id(power_job.job_id)
        assert succeeded is not None
        assert succeeded.status == "succeeded"
        assert succeeded.progress_pct == 100
        assert succeeded.dataset_id is not None

        dup_result = await service.execute_plan(power_plan_b)
        assert any("matches previously ingested dataset" in w for w in dup_result.warnings)

        cancel_job = HarmonizationJob(
            job_id=uuid4(),
            plan=power_plan_b,
            status="pending",
            created_at=t0 + timedelta(seconds=20),
            updated_at=t0 + timedelta(seconds=20),
        )
        await jobs.create(cancel_job)

        class _CancellingService:
            async def execute_plan(self, *_args: object, **_kwargs: object) -> object:
                raise asyncio.CancelledError

        cancel_runner = WorkerRunner(
            service=_CancellingService(),  # type: ignore[arg-type]
            jobs=jobs,
            lifecycle=lifecycle,
            clock=lambda: t0 + timedelta(seconds=21),
        )
        with pytest.raises(asyncio.CancelledError):
            await cancel_runner.run_once()
        cancelled = await jobs.get_by_id(cancel_job.job_id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.error_category == "cancelled"
    finally:
        await engine.dispose()


async def test_worker_maintenance_runs_expired_derived_lifecycle_sweep() -> None:
    """Worker maintenance must request expired-derived cleanup, not only raw protection."""
    calls: list[dict[str, object]] = []

    class _RecordingLifecycle:
        async def run_maintenance_cycle(self, **kwargs: object) -> None:
            calls.append(kwargs)

    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    runner = WorkerRunner(
        service=object(),  # type: ignore[arg-type]
        jobs=object(),  # type: ignore[arg-type]
        lifecycle=_RecordingLifecycle(),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    await runner.run_maintenance()

    assert calls == [{"dry_run": False, "include_expired_derived": True, "now": now}]
