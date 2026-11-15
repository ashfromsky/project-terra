"""Unit tests for Cloud Optimized GeoTIFF (COG) publishing pipeline."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rio_cogeo.cogeo import cog_validate

from geospatial_harmonization.application.cog_publisher import (
    CogPublisher,
    _to_physical_array,
)
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
from geospatial_harmonization.infrastructure.storage import LocalObjectStore
from geospatial_harmonization.readers import build_default_reader_registry


def _make_synthetic_modis_dataset(
    tmp_path: Path,
    raw_data: np.ndarray,
    scale_factor: float = 0.0001,
    nodata: int = -3000,
) -> tuple[SpatialDataset, Path]:
    h, w = raw_data.shape
    tif_path = tmp_path / "modis_raw.tif"
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
        tif_path,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype=str(raw_data.dtype),
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as f:
        f.write(raw_data, 1)
        f.set_band_description(1, "250m_16_days_NDVI")

    asset = AssetReference(
        asset_id="modis-raw-asset",
        uri=f"file://{tif_path}",
        data_format="geotiff",
        media_type="image/tiff",
    )
    var_spec = VariableSpec(
        name="250m_16_days_NDVI",
        units="unitless",
        dtype=str(raw_data.dtype),
        dimensions=("lat", "lon"),
        semantics="continuous_intensive",
        nodata=nodata,
        scale_factor=scale_factor,
        valid_range=(-2000.0, 10000.0),
        grid=grid,
    )
    dataset = SpatialDataset(
        dataset_id=uuid4(),
        source_id="MOD13Q1.061",
        provider="lpdaac",
        product="MOD13Q1",
        variables={"250m_16_days_NDVI": var_spec},
        units={"250m_16_days_NDVI": "unitless"},
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
            provider="lpdaac",
            product="MOD13Q1",
            product_version="061",
            retrieved_at=datetime.now(UTC),
            software_version="0.1.0",
        ),
    )
    return dataset, tif_path


async def test_publish_modis_raw_integer_to_cog(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    storage = LocalObjectStore(storage_root)
    readers = build_default_reader_registry()

    raw_arr = np.array(
        [
            [7500, 8000, -3000],
            [2000, 5000, 9000],
        ],
        dtype=np.int16,
    )
    dataset, _ = _make_synthetic_modis_dataset(tmp_path, raw_arr)

    publisher = CogPublisher(storage=storage, readers=readers)
    result = await publisher.get_or_publish_cog(dataset, variable="250m_16_days_NDVI")

    assert result.is_valid_cog is True
    assert result.is_reused is False
    assert result.storage_key.startswith(f"cogs/{dataset.dataset_id}/")

    # Validate output file is a true COG
    assert result.local_path is not None
    assert result.local_path.exists()
    is_valid, errors, _ = cog_validate(result.local_path, strict=False)
    assert is_valid is True
    assert errors == []

    # Verify physical values in COG
    with rasterio.open(result.local_path) as src:
        assert src.crs.to_epsg() == 3857
        cog_arr = src.read(1)
        # Nodata should be NaN
        valid_vals = cog_arr[np.isfinite(cog_arr)]
        assert len(valid_vals) > 0
        # Physical values must be within [-0.2, 1.0], not raw integer 2000..8000
        assert valid_vals.min() >= -0.2
        assert valid_vals.max() <= 1.0


async def test_cog_publisher_idempotency(tmp_path: Path) -> None:
    storage = LocalObjectStore(tmp_path / "storage")
    readers = build_default_reader_registry()

    raw_arr = np.array([[6000, 7000], [5000, 8000]], dtype=np.int16)
    dataset, _ = _make_synthetic_modis_dataset(tmp_path, raw_arr)

    publisher = CogPublisher(storage=storage, readers=readers)
    res1 = await publisher.get_or_publish_cog(dataset, variable="250m_16_days_NDVI")
    assert res1.is_reused is False

    # Second call must reuse existing COG without re-running translation
    res2 = await publisher.get_or_publish_cog(dataset, variable="250m_16_days_NDVI")
    assert res2.is_reused is True
    assert res2.storage_key == res1.storage_key


def test_physical_array_conversion_guards_against_double_scaling() -> None:
    raw_int = np.array([5000, 8000, -3000], dtype=np.int16)
    spec = VariableSpec(
        name="ndvi",
        units="unitless",
        dtype="int16",
        dimensions=("y", "x"),
        semantics="continuous_intensive",
        scale_factor=0.0001,
        nodata=-3000,
        valid_range=(-2000.0, 10000.0),
    )
    dataset, _ = _make_synthetic_modis_dataset(Path("/tmp"), raw_int.reshape(1, 3))

    phys, _nodata = _to_physical_array(raw_int, spec, dataset)
    assert np.isclose(phys[0], 0.5)
    assert np.isclose(phys[1], 0.8)
    assert np.isnan(phys[2])

    # If array is already float32 physical values, do not scale again
    already_phys = np.array([0.5, 0.8, np.nan], dtype=np.float32)
    spec_float = VariableSpec(
        name="ndvi",
        units="unitless",
        dtype="float32",
        dimensions=("y", "x"),
        semantics="continuous_intensive",
        scale_factor=1.0,
        nodata=np.nan,
        valid_range=(-0.2, 1.0),
    )
    phys2, _ = _to_physical_array(already_phys, spec_float, dataset)
    assert np.isclose(phys2[0], 0.5)
    assert np.isclose(phys2[1], 0.8)
    assert np.isnan(phys2[2])
