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
        sync_body = sync_resp.json()
        assert all(asset["uri"] is None for asset in sync_body["output_assets"])
        assert str(tmp_path) not in sync_resp.text
        assert (await client.get(f"/api/v1/jobs/{uuid4()}")).status_code == 404
        assert (await client.get(f"/api/v1/datasets/{uuid4()}")).status_code == 404


async def test_v1_providers_discover_idempotency_cancel_and_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import socket

    from httpx import MockTransport, Response
    from pydantic import SecretStr

    from geospatial_harmonization.handlers import build_default_handler_registry

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    secret_token = "super-secret-earthdata-bearer-xyz"
    cmr_payload = {
        "feed": {
            "entry": [
                {
                    "id": "G123456-LPCLOUD",
                    "producer_granule_id": "MOD13Q1.A2026182.h20v03.061.2026199.hdf",
                    "title": "MOD13Q1.A2026182",
                    "time_start": "2026-07-01T00:00:00Z",
                    "time_end": "2026-07-17T00:00:00Z",
                    "boxes": ["49.5 29.5 51.0 31.5"],
                    "links": [
                        {
                            "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                            "href": "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MOD13Q1.061/MOD13Q1.hdf?token=leaked-query",
                        }
                    ],
                }
            ]
        }
    }

    transport = MockTransport(lambda _r: Response(200, json=cmr_payload))
    cfg = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'prov.db'}",
        local_storage_dir=tmp_path / "store",
        earthdata_token=SecretStr(secret_token),
        modis_enabled=True,
        gpm_enabled=False,
        smap_enabled=True,
        nasa_power_enabled=True,
        generic_handler_allowed_hosts=["data.example.org"],
    )
    app = create_app(cfg)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        app.state.handlers = build_default_handler_registry(
            settings=cfg,
            reader_registry=app.state.readers,
            raw_dir=tmp_path / "raw",
            transport=transport,
        )

        prov_resp = await client.get("/api/v1/providers")
        assert prov_resp.status_code == 200
        assert secret_token not in prov_resp.text
        by_name = {item["provider"]: item for item in prov_resp.json()}
        assert by_name["modis"]["status"] == "ready"
        assert by_name["modis"]["auth_configured"] is True
        assert by_name["gpm_imerg"]["status"] == "disabled"
        assert by_name["nasa_power"]["status"] == "ready"
        assert by_name["nasa_power"]["auth_required"] is False
        assert by_name["modis"]["registered_products"] == ["MOD11A2.061", "MOD13Q1.061"]
        assert len(by_name["modis"]["products"]) == 2

        caps = (await client.get("/api/v1/capabilities")).json()
        assert len(caps["providers"]) == len(prov_resp.json())

        modis_disc = await client.post(
            "/api/v1/discover",
            json={
                "provider": "modis",
                "product": "MOD13Q1.061",
                "bbox": [30.0, 50.0, 31.0, 51.0],
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-17T00:00:00Z",
                "limit": 5,
            },
        )
        assert modis_disc.status_code == 200
        disc_body = modis_disc.json()
        assert disc_body["count"] == 1
        assert (
            disc_body["observations"][0]["observation_id"]
            == "MOD13Q1.A2026182.h20v03.061.2026199.hdf"
        )
        assert "leaked-query" not in disc_body["observations"][0]["access_hint"]

        power_disc = await client.post(
            "/api/v1/discover",
            json={
                "provider": "nasa_power",
                "product": "power_daily",
                "bbox": [29.0, 49.0, 32.0, 52.0],
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-05T00:00:00Z",
            },
        )
        assert power_disc.status_code == 200
        assert power_disc.json()["observations"][0]["query_mode"] == "regional"

        disabled_disc = await client.post(
            "/api/v1/discover",
            json={
                "provider": "gpm_imerg",
                "product": "GPM_3IMERGHH.07",
                "bbox": [30.0, 50.0, 31.0, 51.0],
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-02T00:00:00Z",
            },
        )
        assert disabled_disc.status_code == 503
        assert disabled_disc.json()["error_category"] == "provider_disabled"

        generic_disc = await client.post(
            "/api/v1/discover",
            json={
                "provider": "generic",
                "product": "custom",
                "bbox": [30.0, 50.0, 31.0, 51.0],
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-02T00:00:00Z",
            },
        )
        assert generic_disc.status_code == 422

        job_req = {
            "provider": "nasa_power",
            "product": "power_daily",
            "request_payload": {
                "product": "power_daily",
                "mode": "point",
                "latitude": 50.0,
                "longitude": 30.0,
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
                "parameters": ["PRECTOTCORR"],
            },
        }
        j1 = await client.post("/api/v1/jobs", json=job_req)
        j2 = await client.post("/api/v1/jobs", json=job_req)
        assert j1.status_code == 202 and j2.status_code == 202
        assert j1.json()["job_id"] == j2.json()["job_id"]
        assert j1.json()["idempotency_key"] is not None

        j3 = await client.post("/api/v1/jobs", json={**job_req, "allow_duplicate": True})
        assert j3.status_code == 202
        assert j3.json()["job_id"] != j1.json()["job_id"]

        cancelled = await client.post(
            f"/api/v1/jobs/{j3.json()['job_id']}/cancel",
            json={"reason": "No longer needed"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["error_category"] == "cancelled"

        disabled_job = await client.post(
            "/api/v1/jobs",
            json={
                "provider": "gpm_imerg",
                "product": "GPM_3IMERGHH.07",
                "request_payload": {},
            },
        )
        assert disabled_job.status_code == 503

        sample_power_json = {
            "properties": {"parameter": {"PRECTOTCORR": {"20260701": 1.5, "20260702": 0.0}}},
            "geometry": {"coordinates": [30.0, 50.0, 100.0]},
            "parameters": {"PRECTOTCORR": {"units": "mm/day", "longname": "Precipitation"}},
            "header": {"fill_value": -999.0},
        }
        app.state.handlers = build_default_handler_registry(
            settings=cfg,
            reader_registry=app.state.readers,
            raw_dir=tmp_path / "raw",
            transport=MockTransport(lambda _r: Response(200, json=sample_power_json)),
        )
        app.state.harmonization_service._handlers = app.state.handlers
        from geospatial_harmonization.worker import WorkerRunner

        worker = WorkerRunner(service=app.state.harmonization_service, jobs=app.state.job_repo)
        assert await worker.run_once() is True
        done = (await client.get(f"/api/v1/jobs/{j1.json()['job_id']}")).json()
        assert done["status"] == "succeeded" and done["progress_pct"] == 100

        cancel_done = await client.post(f"/api/v1/jobs/{done['job_id']}/cancel")
        assert cancel_done.status_code == 409

        prov_endpoint = await client.get(f"/api/v1/datasets/{done['dataset_id']}/provenance")
        assert prov_endpoint.status_code == 200
        prov_data = prov_endpoint.json()
        assert prov_data["provider"] == "nasa_power"
        assert prov_data["granule_id"] is not None
        assert str(tmp_path) not in prov_endpoint.text
        assert all(a["uri"] is None for a in prov_data["assets"])
