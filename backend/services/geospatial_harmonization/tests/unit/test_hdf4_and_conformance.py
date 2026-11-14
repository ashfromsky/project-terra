"""Unit tests for HDF4Reader and full 7-format Reader conformance matrix."""

import json
from pathlib import Path

import h5py
import netCDF4
import numpy as np
import pytest
import rasterio
import zarr
from pyhdf.SD import SD, SDC
from rasterio.transform import from_origin

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
)
from geospatial_harmonization.readers import (
    AssetDecodeError,
    HDF4Reader,
    build_default_reader_registry,
)


def test_hdf4_reader_decodes_hdfeos_sinusoidal_and_protects_qa(tmp_path: Path) -> None:
    hdf_path = tmp_path / "MOD13Q1_sample.hdf"
    sd = SD(str(hdf_path), SDC.WRITE | SDC.CREATE)
    ndvi = sd.create("NDVI", SDC.INT16, (2, 3))
    ndvi.dim(0).setname("YDim")
    ndvi.dim(1).setname("XDim")
    ndvi[:] = np.array([[5000, 7000, -3000], [4000, 6000, 8000]], dtype=np.int16)
    ndvi.attr("_FillValue").set(SDC.INT16, -3000)
    ndvi.attr("scale_factor").set(SDC.FLOAT64, 0.0001)
    ndvi.endaccess()

    qa = sd.create("pixel_reliability", SDC.UINT8, (2, 3))
    qa.dim(0).setname("YDim")
    qa.dim(1).setname("XDim")
    qa[:] = np.array([[0, 0, 255], [0, 1, 0]], dtype=np.uint8)
    qa.attr("scale_factor").set(SDC.FLOAT64, 2.0)
    qa.endaccess()

    meta = (
        "Projection=GCTP_SNSOID\nXDim=3\nYDim=2\n"
        "UpperLeftPointMtrs=(0.0,500.0)\nLowerRightMtrs=(750.0,0.0)\n"
    )
    sd.attr("StructMetadata.0").set(SDC.CHAR, meta)
    sd.end()

    registry = build_default_reader_registry()
    decoded = registry.read(
        AssetReference("h4-1", hdf_path.as_uri(), "hdf4", "application/x-hdf"), hdf_path
    )
    assert decoded.crs is not None and "Sinusoidal" in decoded.crs
    assert decoded.grid is not None and (decoded.grid.width, decoded.grid.height) == (3, 2)
    assert decoded.grid.resolution_x == pytest.approx(250.0)
    assert decoded.variables["NDVI"].scale_factor == pytest.approx(0.0001)
    assert decoded.variables["pixel_reliability"].semantics == "qa_flag"
    assert decoded.variables["pixel_reliability"].scale_factor is None
    assert any("Dropped scaling" in w for w in decoded.warnings)

    corrupt = tmp_path / "corrupt.hdf"
    corrupt.write_bytes(b"\x0e\x03\x13\x01corrupted")
    with pytest.raises(AssetDecodeError, match="Failed to decode HDF4"):
        HDF4Reader().read(
            AssetReference("bad", corrupt.as_uri(), "hdf4", "application/x-hdf"), corrupt
        )


def _write_format_fixture(tmp_path: Path, fmt: DataFormat) -> tuple[AssetReference, Path]:
    if fmt == "geotiff":
        p = tmp_path / "sample.tif"
        with rasterio.open(
            p,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(0, 2, 1, 1),
        ) as dst:
            dst.write(np.ones((2, 2), dtype=np.float32), 1)
            dst.set_band_description(1, "val")
    elif fmt == "netcdf":
        p = tmp_path / "sample.nc"
        with netCDF4.Dataset(p, "w") as ds:
            ds.createDimension("y", 2)
            ds.createDimension("x", 2)
            ds.createVariable("val", "f4", ("y", "x"))[:] = np.ones((2, 2), dtype=np.float32)
    elif fmt == "hdf5":
        p = tmp_path / "sample.h5"
        with h5py.File(p, "w") as h5f:
            h5f.create_dataset("val", data=np.ones((2, 2), dtype=np.float32))
    elif fmt == "hdf4":
        p = tmp_path / "sample.hdf"
        sd = SD(str(p), SDC.WRITE | SDC.CREATE)
        s = sd.create("val", SDC.FLOAT32, (2, 2))
        s[:] = np.ones((2, 2), dtype=np.float32)
        s.endaccess()
        sd.end()
    elif fmt == "zarr":
        p = tmp_path / "sample.zarr"
        zarr.open_group(p, mode="w").create_array("val", data=np.ones((2, 2), dtype=np.float32))
    elif fmt == "json":
        p = tmp_path / "sample.json"
        p.write_text(json.dumps([{"lat": 50.0, "lon": 30.0, "val": 1.0}]), encoding="utf-8")
    else:
        p = tmp_path / "sample.csv"
        p.write_text("lat,lon,val\n50.0,30.0,1.0\n", encoding="utf-8")
    return AssetReference(f"f-{fmt}", p.as_uri(), "unknown", "application/octet-stream"), p


@pytest.mark.parametrize("fmt", ["geotiff", "netcdf", "hdf5", "hdf4", "zarr", "json", "csv"])
def test_default_registry_conformance_across_all_seven_formats(
    tmp_path: Path, fmt: DataFormat
) -> None:
    registry = build_default_reader_registry()
    asset, path = _write_format_fixture(tmp_path, fmt)
    decoded = registry.read(asset, path)
    assert isinstance(decoded, DecodedDataset)
    assert decoded.data_format == fmt
    assert "val" in decoded.variables and "val" in decoded.arrays
    with pytest.raises(AssetDecodeError, match="not found"):
        registry.read(asset, path, variables=("nonexistent_var",))
