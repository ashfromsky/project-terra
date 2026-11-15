"""Unit tests for GHS raster PNG tiles, bbox render, and native-pixel point inspection."""

import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from httpx import ASGITransport, AsyncClient
from numpy.typing import NDArray
from rasterio.transform import from_origin

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    ProvenanceRecord,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.main import create_app


def _decode_rgba_png(png_bytes: bytes) -> tuple[int, int, NDArray[np.uint8]]:
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    idat_chunks: list[bytes] = []

    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        chunk_type = png_bytes[offset + 4 : offset + 8]
        chunk_data = png_bytes[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    assert bit_depth == 8
    assert color_type == 6
    raw = zlib.decompress(b"".join(idat_chunks))
    stride = 1 + width * 4
    assert len(raw) == height * stride
    rows = np.frombuffer(raw, dtype=np.uint8).reshape((height, stride))
    assert np.all(rows[:, 0] == 0)
    rgba = rows[:, 1:].reshape((height, width, 4))
    return width, height, rgba


def _build_mod11a2_geotiff(path: Path) -> bytes:
    grid = np.array(
        [
            [15000, 15000, 15500, 15500],
            [15000, 15000, 15500, 15500],
            [14500, 14500, 0, 0],
            [14500, 14500, 0, 0],
        ],
        dtype=np.uint16,
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(0.0, 10.0, 2.5, 2.5),
        nodata=0,
    ) as dst:
        dst.write(grid, 1)
    return path.read_bytes()


def _make_dataset(
    *,
    asset: AssetReference,
    extensions: dict[str, object] | None = None,
) -> SpatialDataset:
    bounds = SpatialBounds(0.0, 0.0, 10.0, 10.0)
    grid = GridSpec("EPSG:4326", 2.5, 2.5, "degree", bounds).resolved()
    temporal = TemporalSpec(
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 9, tzinfo=UTC),
        cadence="eight_day",
        semantics="composite",
        composite_days=8,
    )
    return SpatialDataset(
        dataset_id=uuid4(),
        source_id="modis_terra_lst",
        provider="nasa_earthdata",
        product="MOD11A2.061",
        variables={
            "LST_Day_1km": VariableSpec(
                name="LST_Day_1km",
                units="K",
                dtype="uint16",
                dimensions=("y", "x"),
                semantics="continuous_intensive",
                nodata=0,
                scale_factor=0.02,
                add_offset=0.0,
            )
        },
        units={"LST_Day_1km": "K"},
        spatial_metadata=SpatialMetadata("raster", "EPSG:4326", bounds, grid),
        temporal_metadata=temporal,
        quality_metadata=QualityMetadata("standard", 0.75),
        assets=(asset,),
        provenance=ProvenanceRecord(
            provider="nasa_earthdata",
            product="MOD11A2.061",
            product_version="061",
            retrieved_at=datetime(2024, 6, 10, tzinfo=UTC),
            software_version="0.1.0",
        ),
        extensions=extensions or {},
    )


async def test_raster_tiles_render_and_point_inspection(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'raster_viz.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)
    tif_bytes = _build_mod11a2_geotiff(tmp_path / "mod11a2.tif")

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        stored_asset = await app.state.storage.put_bytes(
            "derived/mod11a2_test.tif",
            tif_bytes,
            media_type="image/tiff",
        )
        dataset = _make_dataset(
            asset=stored_asset,
            extensions={
                "time_series": {
                    "LST_Day_1km": {
                        "timestamps": ["2024-06-01T00:00:00Z", "2024-06-09T00:00:00Z"],
                        "values": [298.0, 300.0],
                    }
                }
            },
        )
        await app.state.dataset_repo.save(dataset)
        dataset_id = str(dataset.dataset_id)

        tile_resp = await client.get(
            f"/api/v1/datasets/{dataset_id}/tiles/0/0/0.png",
            params={"unit_conversion": "kelvin_to_celsius", "vmin": 0.0, "vmax": 50.0},
        )
        assert tile_resp.status_code == 200, tile_resp.text
        assert tile_resp.headers["content-type"].startswith("image/png")
        tile_w, tile_h, tile_rgba = _decode_rgba_png(tile_resp.content)
        assert (tile_w, tile_h) == (256, 256)
        assert np.all(tile_rgba[:, :100, 3] == 0)
        assert np.any(tile_rgba[:, 128:, 3] > 0)

        render_resp = await client.get(
            f"/api/v1/datasets/{dataset_id}/render.png",
            params={
                "bbox": "0,0,10,10",
                "width": 64,
                "height": 64,
                "unit_conversion": "kelvin_to_celsius",
                "vmin": 0.0,
                "vmax": 50.0,
            },
        )
        assert render_resp.status_code == 200
        assert render_resp.headers["content-type"].startswith("image/png")
        render_w, render_h, render_rgba = _decode_rgba_png(render_resp.content)
        assert (render_w, render_h) == (64, 64)
        top_left_rgb = render_rgba[0, 0]
        assert top_left_rgb[3] == 255
        assert np.all(render_rgba[:32, :32] == top_left_rgb)
        assert np.all(render_rgba[32:, 32:, 3] == 0)

        point_ok = await client.get(
            f"/api/v1/datasets/{dataset_id}/point",
            params={"lon": 1.25, "lat": 8.75, "unit_conversion": "kelvin_to_celsius"},
        )
        assert point_ok.status_code == 200
        ok_body = point_ok.json()
        assert ok_body["status"] == "ok"
        assert ok_body["raw_value"] == pytest.approx(15000.0)
        assert ok_body["value"] == pytest.approx(26.85, abs=0.05)
        assert ok_body["unit"] == "°C"
        assert ok_body["pixel_row"] == 0
        assert ok_body["pixel_col"] == 0
        assert len(ok_body["time_series"]) == 2

        point_nodata = await client.get(
            f"/api/v1/datasets/{dataset_id}/point",
            params={"lon": 8.75, "lat": 1.25},
        )
        assert point_nodata.status_code == 200
        assert point_nodata.json()["status"] == "nodata"
        assert point_nodata.json()["value"] is None

        point_outside = await client.get(
            f"/api/v1/datasets/{dataset_id}/point",
            params={"lon": 45.0, "lat": 45.0},
        )
        assert point_outside.status_code == 200
        assert point_outside.json()["status"] == "outside_bounds"
        assert point_outside.json()["value"] is None


async def test_zarr_only_dataset_rejected_from_raster_rendering(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'zarr_reject.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        zarr_asset = AssetReference(
            asset_id="zarr-asset-1",
            uri="file:///derived/cube.zarr",
            data_format="zarr",
            media_type="application/vnd+zarr",
            storage_key="derived/cube.zarr",
        )
        dataset = _make_dataset(asset=zarr_asset)
        await app.state.dataset_repo.save(dataset)
        dataset_id = str(dataset.dataset_id)

        tile_resp = await client.get(f"/api/v1/datasets/{dataset_id}/tiles/0/0/0.png")
        assert tile_resp.status_code == 422

        render_resp = await client.get(
            f"/api/v1/datasets/{dataset_id}/render.png",
            params={"bbox": "0,0,10,10"},
        )
        assert render_resp.status_code == 422

        point_resp = await client.get(
            f"/api/v1/datasets/{dataset_id}/point",
            params={"lon": 1.0, "lat": 1.0},
        )
        assert point_resp.status_code == 422
