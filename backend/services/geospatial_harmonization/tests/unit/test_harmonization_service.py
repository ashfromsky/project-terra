"""Unit tests for HarmonizationService execution pipeline."""

import json
import math
import socket
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
from geospatial_harmonization.domain.models.harmonization import HarmonizationPlan
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import SqlAlchemyDatasetRepository
from geospatial_harmonization.infrastructure.storage import LocalObjectStore


def _geotiff_bytes(path: Path) -> bytes:
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


async def test_harmonization_service_execute_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    tif_bytes = _geotiff_bytes(tmp_path / "src.tif")
    power_json = json.dumps(
        {
            "geometry": {"coordinates": [30.5, 50.4, 150.0]},
            "properties": {"parameter": {"T2M": {"20260701": 22.5}}},
        }
    ).encode("utf-8")

    def dispatch(request: Request) -> Response:
        if "power.larc.nasa.gov" in request.url.host:
            return Response(200, content=power_json, headers={"content-type": "application/json"})
        return Response(200, content=tif_bytes, headers={"content-type": "image/tiff"})

    handlers = build_default_handler_registry(
        settings=Settings(generic_handler_allowed_hosts=["data.example.org"]),
        raw_dir=tmp_path / "raw",
        transport=MockTransport(dispatch),
    )
    storage = LocalObjectStore(tmp_path / "store")
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'svc.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        datasets = SqlAlchemyDatasetRepository(build_session_factory(engine))
        svc = HarmonizationService(handlers=handlers, storage=storage, datasets=datasets)

        res1 = await svc.execute_plan(
            HarmonizationPlan(
                plan_id=uuid4(),
                provider="generic",
                product="custom_tif",
                request_payload={
                    "url": "https://data.example.org/ndvi.tif",
                    "product": "custom_tif",
                    "data_format": "geotiff",
                },
                target_grid=GridSpec(
                    "EPSG:3857",
                    50000.0,
                    50000.0,
                    "meter",
                    SpatialBounds(0.0, 0.0, 200000.0, 200000.0),
                ),
                variables=("band_1",),
            )
        )
        assert res1.quality_report.passed is True
        assert await storage.exists(res1.output_assets[0].asset_id)
        stored = await datasets.get_by_id(res1.dataset.dataset_id)
        assert stored is not None
        assert stored.assets == res1.dataset.assets
        assert stored.spatial_metadata == res1.dataset.spatial_metadata
        assert stored.variables["band_1"].nodata is not None
        assert math.isnan(float(stored.variables["band_1"].nodata))

        res2 = await svc.execute_plan(
            HarmonizationPlan(
                plan_id=uuid4(),
                provider="nasa_power",
                product="nasa_power",
                request_payload={
                    "parameters": ["T2M"],
                    "latitude": 50.4,
                    "longitude": 30.5,
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-01",
                },
            )
        )
        assert res2.quality_report.valid_fraction == pytest.approx(1.0)
        assert await datasets.get_by_id(res2.dataset.dataset_id) is not None
    finally:
        await engine.dispose()
