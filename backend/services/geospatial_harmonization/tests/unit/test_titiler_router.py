"""Tests for TiTiler router and dynamic COG tile serving endpoints."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from rasterio.transform import from_bounds
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

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


def _make_test_cog_dataset(tmp_path: Path) -> tuple[SpatialDataset, Path]:
    h, w = 128, 128
    src_tif = tmp_path / "raw.tif"
    cog_tif = tmp_path / "cog.tif"
    data = (np.ones((1, h, w)) * 0.75).astype(np.float32)
    transform = from_bounds(10.0, 50.0, 11.0, 51.0, w, h)
    bounds = SpatialBounds(10.0, 50.0, 11.0, 51.0)
    grid = GridSpec(
        crs="EPSG:4326",
        resolution_x=1.0 / float(w),
        resolution_y=1.0 / float(h),
        resolution_unit="degree",
        bounds=bounds,
        width=w,
        height=h,
    )

    with rasterio.open(
        src_tif,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
    ) as f:
        f.write(data)
        f.set_band_description(1, "ndvi")

    cog_translate(src_tif, cog_tif, cog_profiles.get("deflate"), nodata=np.nan, quiet=True)

    asset = AssetReference(
        asset_id="test-cog-asset",
        uri=f"file://{cog_tif}",
        data_format="geotiff",
        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
    )
    var_spec = VariableSpec(
        name="ndvi",
        units="unitless",
        dtype="float32",
        dimensions=("lat", "lon"),
        semantics="continuous_intensive",
        nodata=np.nan,
        valid_range=(-0.2, 1.0),
        grid=grid,
    )
    dataset = SpatialDataset(
        dataset_id=uuid4(),
        source_id="TEST_NDVI",
        provider="test_provider",
        product="TEST_PROD",
        variables={"ndvi": var_spec},
        units={"ndvi": "unitless"},
        spatial_metadata=SpatialMetadata(
            representation="raster",
            crs="EPSG:4326",
            bounds=bounds,
            grid=grid,
        ),
        temporal_metadata=TemporalSpec(
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 17, tzinfo=UTC),
            cadence="16-day",
            semantics="composite",
            composite_days=16,
        ),
        quality_metadata=QualityMetadata(qa_policy="standard"),
        assets=(asset,),
        provenance=ProvenanceRecord(
            provider="test_provider",
            product="TEST_PROD",
            product_version="001",
            retrieved_at=datetime.now(UTC),
            software_version="0.1.0",
        ),
    )
    return dataset, cog_tif


def test_titiler_mounted_endpoints(tmp_path: Path) -> None:
    _dataset, cog_path = _make_test_cog_dataset(tmp_path)
    app = create_app()

    with TestClient(app) as client:
        # 1. Info endpoint
        info_res = client.get("/cog/info", params={"url": str(cog_path)})
        assert info_res.status_code == 200
        info_data = info_res.json()
        assert info_data.get("driver") == "GTiff"

        # 2. TileJSON endpoint
        tj_res = client.get("/cog/WebMercatorQuad/tilejson.json", params={"url": str(cog_path)})
        assert tj_res.status_code == 200
        tj_data = tj_res.json()
        assert "tiles" in tj_data

        # 3. Tiles endpoint (zoom 8, x 135, y 86)
        tile_res = client.get(
            "/cog/tiles/WebMercatorQuad/8/135/86.png",
            params={"url": str(cog_path), "rescale": "0,1", "colormap_name": "viridis"},
        )
        assert tile_res.status_code == 200
        assert tile_res.headers.get("content-type") == "image/png"
        assert tile_res.content.startswith(b"\x89PNG\r\n\x1a\n")


async def test_dataset_tilejson_and_zonal_statistics(tmp_path: Path) -> None:
    dataset, _cog_path = _make_test_cog_dataset(tmp_path)
    from geospatial_harmonization.config.settings import Settings

    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'titiler_test.db'}",
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(cfg)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        # Save dataset into app state repo
        await app.state.dataset_repo.save(dataset)

        # 1. Dataset TileJSON
        tj_res = await client.get(f"/api/v1/datasets/{dataset.dataset_id}/tilejson.json")
        assert tj_res.status_code == 200
        tj_body = tj_res.json()
        assert tj_body["tilejson"] == "2.2.0"
        assert tj_body["scheme"] == "xyz"
        assert len(tj_body["tiles"]) == 1
        expected_tile_url = f"/api/v1/datasets/{dataset.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
        assert expected_tile_url in tj_body["tiles"][0]

        # 2. Zonal Statistics on polygon intersecting the raster
        geom = {
            "type": "Polygon",
            "coordinates": [
                [
                    [10.2, 50.2],
                    [10.8, 50.2],
                    [10.8, 50.8],
                    [10.2, 50.8],
                    [10.2, 50.2],
                ]
            ],
        }
        stats_res = await client.post(
            f"/api/v1/datasets/{dataset.dataset_id}/zonal-statistics",
            json={"geometry": geom, "variable": "ndvi"},
        )
        assert stats_res.status_code == 200
        stats_body = stats_res.json()
        assert stats_body["datasetId"] == str(dataset.dataset_id)
        assert stats_body["variableName"] == "ndvi"
        assert stats_body["validPixelCount"] > 0
        assert stats_body["validDataCoverage"] > 0.0
        assert np.isclose(stats_body["mean"], 0.75, atol=0.01)
        assert np.isclose(stats_body["median"], 0.75, atol=0.01)
        assert "histogram" in stats_body
        assert len(stats_body["histogram"]["bins"]) > 0
