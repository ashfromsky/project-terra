"""Tests for FastAPI liveness, readiness, and degraded dependency responses."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from geospatial_harmonization.api.dependencies import get_db_engine
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.infrastructure.database import build_async_engine
from geospatial_harmonization.main import create_app


async def test_health_and_readiness_probes(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        for path in ("/health", "/api/v1/health"):
            res = await client.get(path)
            assert res.status_code == 200
            assert res.json()["status"] == "ok"

        for path in ("/ready", "/api/v1/ready"):
            res = await client.get(path)
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "ready"
            assert body["checks"]["database"]["status"] == "ok"

        bad_engine = build_async_engine("sqlite+aiosqlite:////nonexistent-ghs-dir/bad.db")
        app.dependency_overrides[get_db_engine] = lambda: bad_engine
        try:
            degraded = await client.get("/ready")
            assert degraded.status_code == 503
            assert degraded.json()["status"] == "not_ready"
            assert degraded.json()["checks"]["database"]["status"] == "unavailable"
        finally:
            app.dependency_overrides.clear()
            await bad_engine.dispose()


def _sample_tif_bytes(path: Path) -> bytes:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

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
        dst.write(np.full((4, 4), 1.5, dtype=np.float32), 1)
    return path.read_bytes()


async def test_v1_jobs_harmonize_datasets_and_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import socket
    from uuid import uuid4

    from httpx import MockTransport, Response

    from geospatial_harmonization.application import HarmonizationService
    from geospatial_harmonization.handlers import build_default_handler_registry
    from geospatial_harmonization.worker import WorkerRunner

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _sample_tif_bytes(tmp_path / "src.tif")
    transport = MockTransport(
        lambda _r: Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})
    )
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'v1.db'}",
        local_storage_dir=tmp_path / "store",
        generic_handler_allowed_hosts=["data.example.org"],
    )
    app = create_app(cfg)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        handlers = build_default_handler_registry(
            settings=cfg,
            reader_registry=app.state.readers,
            raw_dir=tmp_path / "raw",
            transport=transport,
        )
        app.state.handlers = handlers
        app.state.harmonization_service = HarmonizationService(
            handlers=handlers,
            storage=app.state.storage,
            datasets=app.state.dataset_repo,
            readers=app.state.readers,
        )

        caps = (await client.get("/api/v1/capabilities")).json()
        assert "modis" in caps["handlers"] and "geotiff" in caps["formats"]

        bad_grid = {
            "provider": "generic",
            "product": "ndvi",
            "target_grid": {
                "crs": "EPSG:4326",
                "resolution_x": 0.3,
                "resolution_y": 0.3,
                "resolution_unit": "degree",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
            },
        }
        assert (await client.post("/api/v1/jobs", json=bad_grid)).status_code == 422

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
        queued = await client.post("/api/v1/jobs", json=payload)
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]
        runner = WorkerRunner(service=app.state.harmonization_service, jobs=app.state.job_repo)
        assert await runner.run_once() is True

        done = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        assert done["status"] == "succeeded" and done["dataset_id"] is not None
        assert (await client.get(f"/api/v1/datasets/{done['dataset_id']}")).status_code == 200
        assert len((await client.get("/api/v1/datasets")).json()) == 1

        sync_resp = await client.post("/api/v1/harmonize", json=payload)
        assert sync_resp.status_code == 200 and sync_resp.json()["quality_report"]["passed"] is True
        assert (await client.get(f"/api/v1/jobs/{uuid4()}")).status_code == 404
        assert (await client.get(f"/api/v1/datasets/{uuid4()}")).status_code == 404
