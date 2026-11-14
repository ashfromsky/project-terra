"""Unit tests for GeoTIFFReader and shared reader decoding helpers."""

import warnings
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import Affine, from_origin

from geospatial_harmonization.domain.models.dataset import AssetReference
from geospatial_harmonization.readers import AssetDecodeError, GeoTIFFReader, ReaderRegistry


def test_geotiff_reader_decodes_multiband_lazy_and_preserves_qa_unscaled(tmp_path: Path) -> None:
    tif_path = tmp_path / "sample.tif"
    transform = from_origin(500000.0, 5600000.0, 250.0, 250.0)
    ndvi_raw = np.array([[5000, 7500, -3000], [2500, 8000, 6000]], dtype=np.int16)
    qa_raw = np.array([[0, 1, 255], [0, 0, 2]], dtype=np.uint8)

    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=2,
        width=3,
        count=2,
        dtype="int16",
        crs="EPSG:32636",
        transform=transform,
        nodata=-3000,
    ) as dst:
        dst.write(ndvi_raw, 1)
        dst.write(qa_raw.astype(np.int16), 2)
        dst.set_band_description(1, "NDVI")
        dst.set_band_description(2, "QA_Reliability")
        dst.scales = (0.0001, 0.5)
        dst.offsets = (0.0, 10.0)
        dst.units = ("1", "bitmask")

    asset = AssetReference("tif-1", tif_path.as_uri(), "geotiff", "image/tiff")
    registry = ReaderRegistry((GeoTIFFReader(),))
    decoded = registry.read(asset, tif_path)

    assert decoded.crs == "EPSG:32636"
    assert decoded.grid is not None
    assert decoded.grid.width == 3 and decoded.grid.height == 2
    assert decoded.grid.resolution_unit == "meter"
    assert decoded.variables["NDVI"].scale_factor == 0.0001
    assert decoded.variables["NDVI"].semantics == "continuous_intensive"
    assert decoded.variables["QA_Reliability"].semantics == "qa_flag"
    assert decoded.variables["QA_Reliability"].scale_factor is None
    assert any("Dropped scaling" in w for w in decoded.warnings)
    np.testing.assert_array_equal(decoded.arrays["NDVI"], ndvi_raw)

    lazy = registry.read(asset, tif_path, variables=("NDVI",))
    assert list(lazy.variables.keys()) == ["NDVI"]
    assert list(lazy.arrays.keys()) == ["NDVI"]


def test_geotiff_reader_handles_rotated_and_unreferenced_without_inventing_crs(
    tmp_path: Path,
) -> None:
    rotated_path = tmp_path / "rotated.tif"
    rotated = Affine(10.0, 2.0, 100.0, -2.0, -10.0, 200.0)
    with rasterio.open(
        rotated_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=rotated,
    ) as dst:
        dst.write(np.ones((2, 2), dtype=np.float32), 1)

    reader = GeoTIFFReader()
    rot_asset = AssetReference("rot", rotated_path.as_uri(), "geotiff", "image/tiff")
    rot_decoded = reader.read(rot_asset, rotated_path)
    assert rot_decoded.crs == "EPSG:4326"
    assert rot_decoded.grid is not None
    assert rot_decoded.grid.alignment_policy == "explicit_transform"

    unref_path = tmp_path / "unref.tif"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(
            unref_path, "w", driver="GTiff", height=2, width=2, count=1, dtype="uint8"
        ) as dst:
            dst.write(np.zeros((2, 2), dtype=np.uint8), 1)

    unref_asset = AssetReference("unref", unref_path.as_uri(), "geotiff", "image/tiff")
    unref_decoded = reader.read(unref_asset, unref_path)
    assert unref_decoded.crs is None
    assert unref_decoded.grid is None
    assert any("No explicit CRS" in w for w in unref_decoded.warnings)

    corrupt = tmp_path / "corrupt.tif"
    corrupt.write_bytes(b"II*\x00corrupted_payload")
    with pytest.raises(AssetDecodeError, match="Failed to decode GeoTIFF"):
        reader.read(AssetReference("bad", corrupt.as_uri(), "geotiff", "image/tiff"), corrupt)
