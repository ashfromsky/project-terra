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


async def test_non_raster_dataset_rejected_and_missing_asset_returns_404(tmp_path: Path) -> None:
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
        json_asset = AssetReference(
            asset_id="json-asset-1",
            uri="file:///derived/series.json",
            data_format="json",
            media_type="application/json",
            storage_key="derived/series.json",
        )
        json_ds = _make_dataset(asset=json_asset)
        await app.state.dataset_repo.save(json_ds)
        json_id = str(json_ds.dataset_id)

        tile_resp = await client.get(f"/api/v1/datasets/{json_id}/tiles/0/0/0.png")
        assert tile_resp.status_code == 422

        render_resp = await client.get(
            f"/api/v1/datasets/{json_id}/render.png",
            params={"bbox": "0,0,10,10"},
        )
        assert render_resp.status_code == 422

        point_resp = await client.get(
            f"/api/v1/datasets/{json_id}/point",
            params={"lon": 1.0, "lat": 1.0},
        )
        assert point_resp.status_code == 422

        missing_zarr = AssetReference(
            asset_id="zarr-missing-1",
            uri="file:///derived/missing.zarr",
            data_format="zarr",
            media_type="application/vnd+zarr",
            storage_key="derived/missing.zarr",
        )
        missing_ds = _make_dataset(asset=missing_zarr)
        await app.state.dataset_repo.save(missing_ds)
        missing_resp = await client.get(f"/api/v1/datasets/{missing_ds.dataset_id}/tiles/0/0/0.png")
        assert missing_resp.status_code == 404


async def test_zarr_raster_renders_tiles_and_point_query(tmp_path: Path) -> None:
    import zarr

    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'zarr_ok.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)

    zarr_path = tmp_path / "ndvi.zarr"
    root = zarr.open_group(zarr_path, mode="w")
    root.attrs["crs"] = "EPSG:4326"
    x_arr = root.create_array("x", data=np.array([1.25, 3.75, 6.25, 8.75], dtype=np.float64))
    x_arr.attrs["_ARRAY_DIMENSIONS"] = ["x"]
    x_arr.attrs["units"] = "degrees_east"
    y_arr = root.create_array("y", data=np.array([8.75, 6.25, 3.75, 1.25], dtype=np.float64))
    y_arr.attrs["_ARRAY_DIMENSIONS"] = ["y"]
    y_arr.attrs["units"] = "degrees_north"
    ndvi_arr = root.create_array(
        "ndvi",
        data=np.array(
            [
                [0.65, 0.70, 0.75, 0.80],
                [0.60, 0.65, 0.70, 0.75],
                [0.50, 0.55, np.nan, np.nan],
                [0.40, 0.45, np.nan, np.nan],
            ],
            dtype=np.float32,
        ),
    )
    ndvi_arr.attrs["_ARRAY_DIMENSIONS"] = ["y", "x"]
    ndvi_arr.attrs["units"] = "1"

    bounds = SpatialBounds(0.0, 0.0, 10.0, 10.0)
    grid = GridSpec("EPSG:4326", 2.5, 2.5, "degree", bounds).resolved()
    temporal = TemporalSpec(
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 17, tzinfo=UTC),
        cadence="sixteen_day",
        semantics="composite",
        composite_days=16,
    )
    base = _make_dataset(
        asset=AssetReference(
            asset_id="zarr-ndvi-1",
            uri=zarr_path.as_uri(),
            data_format="zarr",
            media_type="application/vnd+zarr",
        )
    )
    dataset = SpatialDataset(
        dataset_id=uuid4(),
        source_id="mod13q1_zarr",
        provider="modis",
        product="MOD13Q1.061",
        variables={
            "ndvi": VariableSpec(
                name="ndvi",
                units="1",
                dtype="float32",
                dimensions=("y", "x"),
                semantics="continuous_intensive",
                grid=grid,
            )
        },
        units={"ndvi": "1"},
        spatial_metadata=SpatialMetadata("raster", "EPSG:4326", bounds, grid),
        temporal_metadata=temporal,
        assets=base.assets,
        provenance=base.provenance,
        quality_metadata=base.quality_metadata,
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await app.state.dataset_repo.save(dataset)
        ds_id = str(dataset.dataset_id)

        tile_resp = await client.get(
            f"/api/v1/datasets/{ds_id}/tiles/2/2/1.png",
            params={"variable": "ndvi", "colormap": "ndvi", "vmin": 0.0, "vmax": 1.0},
        )
        assert tile_resp.status_code == 200
        w, h, rgba = _decode_rgba_png(tile_resp.content)
        assert (w, h) == (256, 256)
        assert np.any(rgba[:, :, 3] > 0)

        pt_resp = await client.get(
            f"/api/v1/datasets/{ds_id}/point",
            params={"lon": 1.25, "lat": 8.75, "variable": "ndvi"},
        )
        assert pt_resp.status_code == 200
        pt = pt_resp.json()
        assert pt["status"] == "ok"
        assert pt["value"] == pytest.approx(0.65, abs=1e-4)


async def test_lst_float_geotiff_never_double_scales_or_double_converts_and_qa_rejects(
    tmp_path: Path,
) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'lst_qa.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)

    tif_path = tmp_path / "lst_float.tif"
    # Band 1: already-scaled Kelvin values (300.0 K = 26.85 C, and an invalid -500.0 K)
    # Band 2: QC_Day bitmask (0 = good, 3 = bad mandatory QA)
    lst_grid = np.array([[300.0, 305.0], [310.0, -500.0]], dtype=np.float32)
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0, 10.0, 5.0, 5.0),
    ) as dst:
        dst.write(lst_grid, 1)

    asset = AssetReference(
        asset_id="lst-float-1",
        uri=tif_path.as_uri(),
        data_format="geotiff",
        media_type="image/tiff",
    )
    dataset = _make_dataset(asset=asset)
    # _make_dataset has scale_factor=0.02, valid_range=[150, 380] on VariableSpec;
    # float32 GeoTIFF must NOT apply 0.02 again!
    dataset = SpatialDataset(
        dataset_id=dataset.dataset_id,
        source_id=dataset.source_id,
        provider="modis",
        product="MOD11A2.061",
        variables={
            "LST_Day_1km": VariableSpec(
                name="LST_Day_1km",
                units="K",
                dtype="float32",
                dimensions=("y", "x"),
                semantics="continuous_intensive",
                scale_factor=0.02,
                valid_range=(150.0, 380.0),
            )
        },
        units={"LST_Day_1km": "K"},
        spatial_metadata=dataset.spatial_metadata,
        temporal_metadata=dataset.temporal_metadata,
        assets=(asset,),
        provenance=dataset.provenance,
        quality_metadata=dataset.quality_metadata,
        extensions={
            "time_series": {
                "LST_Day_1km": {
                    "timestamps": ["2024-06-01T00:00:00Z"],
                    "values": [300.0],
                }
            }
        },
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await app.state.dataset_repo.save(dataset)
        ds_id = str(dataset.dataset_id)

        # Valid pixel (300.0 K -> 26.85 C, time_series also converted to 26.85 C)
        ok_resp = await client.get(
            f"/api/v1/datasets/{ds_id}/point",
            params={"lon": 2.5, "lat": 7.5, "unit_conversion": "kelvin_to_celsius"},
        )
        assert ok_resp.status_code == 200
        ok_data = ok_resp.json()
        assert ok_data["status"] == "ok"
        assert ok_data["unit"] == "°C"
        assert ok_data["value"] == pytest.approx(26.85, abs=1e-2)
        assert ok_data["time_series"][0]["value"] == pytest.approx(26.85, abs=1e-2)

        # Out-of-range physical pixel (-500.0 K) must be rejected as nodata
        bad_resp = await client.get(
            f"/api/v1/datasets/{ds_id}/point",
            params={"lon": 7.5, "lat": 2.5, "unit_conversion": "kelvin_to_celsius"},
        )
        assert bad_resp.status_code == 200
        bad_data = bad_resp.json()
        assert bad_data["status"] == "nodata"
        assert bad_data["value"] is None

        # Out-of-bounds coordinate must return outside_bounds
        oob_resp = await client.get(
            f"/api/v1/datasets/{ds_id}/point",
            params={"lon": 50.0, "lat": 50.0, "unit_conversion": "kelvin_to_celsius"},
        )
        assert oob_resp.status_code == 200
        oob_data = oob_resp.json()
        assert oob_data["status"] == "outside_bounds"
        assert oob_data["value"] is None

        # Derived dataset endpoint persists AOI GeoTIFF, renders PNG, and answers point query
        derived_resp = await client.post(
            "/api/v1/datasets/derived",
            json={
                "product": "TERRA-NDVI-ANOM",
                "variable_name": "ndvi_zscore",
                "units": "z-score",
                "bbox_wgs84": [23.0, 48.0, 25.0, 49.5],
                "scope": "aoi",
                "scalar_value": -1.75,
                "timestamps": ["2024-06-01T00:00:00Z"],
                "time_series_values": [-1.75],
            },
        )
        assert derived_resp.status_code == 201
        derived_ds = derived_resp.json()
        derived_id = derived_ds["dataset_id"]
        assert derived_ds["extensions"]["scope"] == "aoi"

        derived_pt = await client.get(
            f"/api/v1/datasets/{derived_id}/point",
            params={"lon": 24.0, "lat": 48.75},
        )
        assert derived_pt.status_code == 200
        assert derived_pt.json()["status"] == "ok"
        assert derived_pt.json()["value"] == pytest.approx(-1.75, abs=1e-4)

        derived_tile = await client.get(
            f"/api/v1/datasets/{derived_id}/render.png",
            params={"bbox": "23,48,25,49.5", "vmin": -3, "vmax": 3},
        )
        assert derived_tile.status_code == 200
        assert derived_tile.content[:8] == b"\x89PNG\r\n\x1a\n"
