"""Numerical and scientific unit tests for universal raster warping operations."""

from pathlib import Path

import numpy as np
import pytest

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import AssetReference, VariableSpec
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.readers import GeoTIFFReader
from geospatial_harmonization.transformations import (
    check_upsampling_warning,
    warp_variable,
    write_variable_geotiff,
)


def _grid(crs: str, res: float, b: tuple[float, float, float, float]) -> GridSpec:
    unit = "degree" if crs == "EPSG:4326" else "meter"
    return GridSpec(crs, res, res, unit, SpatialBounds(*b), pixel_convention="corner").resolved()


def test_warp_orients_lon_lat_flips_ascending_y_and_scales_before_resampling() -> None:
    src_grid = _grid("EPSG:4326", 1.0, (0.0, 0.0, 2.0, 2.0))
    dst_grid = _grid("EPSG:4326", 1.0, (0.0, 0.0, 2.0, 2.0))
    raw = np.array([[[1000, 9000], [3000, -3000]]], dtype=np.int16)
    coords = {"lon": (0.5, 1.5), "lat": (0.5, 1.5)}
    spec = VariableSpec(
        "NDVI",
        "1",
        "int16",
        ("time", "lon", "lat"),
        "continuous_intensive",
        nodata=-3000,
        scale_factor=0.0001,
    )

    warped, out_dims = warp_variable(raw, spec, src_grid, dst_grid, "bilinear", coords)
    assert out_dims == ("time", "y", "x")
    assert warped.data[0, 0, 0] == pytest.approx(0.9, abs=1e-4)
    assert np.isnan(warped.data[0, 0, 1])
    assert warped.data[0, 1, 0] == pytest.approx(0.1, abs=1e-4)
    assert warped.data[0, 1, 1] == pytest.approx(0.3, abs=1e-4)
    assert (warped.valid_pixels, warped.total_pixels) == (3, 4)


def test_warp_conserves_extensive_sum_and_preserves_discrete_qa_bits() -> None:
    src_grid = _grid("EPSG:3857", 100.0, (0.0, 0.0, 400.0, 400.0))
    coarse_grid = _grid("EPSG:3857", 200.0, (0.0, 0.0, 400.0, 400.0))
    fine_grid = _grid("EPSG:3857", 50.0, (0.0, 0.0, 400.0, 400.0))

    flux = np.ones((4, 4), dtype=np.float32)
    flux_spec = VariableSpec("mass", "kg", "float32", ("y", "x"), "continuous_extensive")
    downsampled, _ = warp_variable(flux, flux_spec, src_grid, coarse_grid, "sum", {})
    upsampled, _ = warp_variable(flux, flux_spec, src_grid, fine_grid, "sum", {})
    assert float(np.nansum(downsampled.data)) == pytest.approx(16.0, rel=1e-5)
    assert float(np.nansum(upsampled.data)) == pytest.approx(16.0, rel=1e-5)

    qa = np.array([[0, 8, 1, 255], [0, 0, 8, 8], [1, 1, 0, 0], [8, 8, 0, 255]], dtype=np.uint8)
    qa_spec = VariableSpec("QC", "bitmask", "uint8", ("y", "x"), "qa_flag", nodata=255)
    qa_warped, _ = warp_variable(qa, qa_spec, src_grid, fine_grid, "nearest", {})
    assert set(np.unique(qa_warped.data).tolist()).issubset({0, 1, 8, 255})


def test_upsampling_warning_shape_guard_and_geotiff_roundtrip(tmp_path: Path) -> None:
    coarse_geo = _grid("EPSG:4326", 0.25, (10.0, 50.0, 11.0, 51.0))
    fine_merc = _grid("EPSG:3857", 1000.0, (1113194.0, 6446275.0, 1117194.0, 6450275.0))
    warn = check_upsampling_warning(coarse_geo, fine_merc)
    assert warn is not None and "upsampling" in warn.lower()

    data_grid = _grid("EPSG:3857", 100.0, (0.0, 0.0, 200.0, 200.0))
    bad_spec = VariableSpec("T", "K", "float32", ("y", "x"), "continuous_intensive")
    with pytest.raises(IncompatibleDatasetError, match="spatial shape"):
        warp_variable(
            np.ones((3, 3), dtype=np.float32), bad_spec, data_grid, data_grid, "bilinear", {}
        )

    warped, _ = warp_variable(
        np.full((2, 2), 295.5, dtype=np.float32), bad_spec, data_grid, data_grid, "nearest", {}
    )
    out_tif = tmp_path / "out.tif"
    write_variable_geotiff(out_tif, warped, data_grid, "T", {"GHS_METHOD": "nearest"})
    decoded = GeoTIFFReader().read(
        AssetReference("o1", out_tif.as_uri(), "geotiff", "image/tiff"), out_tif
    )
    assert decoded.crs == "EPSG:3857"
    np.testing.assert_allclose(decoded.arrays["T"], 295.5)
