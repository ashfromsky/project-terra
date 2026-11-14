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
