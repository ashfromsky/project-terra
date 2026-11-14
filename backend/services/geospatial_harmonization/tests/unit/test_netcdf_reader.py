"""Unit tests for NetCDFReader preserving dimension order, CF grids, and QA safety."""

from pathlib import Path

import netCDF4
import numpy as np
import pytest

from geospatial_harmonization.domain.models.dataset import AssetReference
from geospatial_harmonization.readers import AssetDecodeError, NetCDFReader, ReaderRegistry


def test_netcdf4_grouped_preserves_lon_lat_order_and_blocks_qa_scaling(tmp_path: Path) -> None:
    nc_path = tmp_path / "gpm_sample.nc4"
    with netCDF4.Dataset(nc_path, mode="w", format="NETCDF4") as ds:
        grid_grp = ds.createGroup("Grid")
        grid_grp.createDimension("time", 1)
        grid_grp.createDimension("lon", 4)
        grid_grp.createDimension("lat", 3)

        lon = grid_grp.createVariable("lon", "f4", ("lon",))
        lon[:] = np.array([-10.05, -9.95, -9.85, -9.75], dtype=np.float32)
        lon.units = "degrees_east"
        lon.axis = "X"

        lat = grid_grp.createVariable("lat", "f4", ("lat",))
        lat[:] = np.array([50.05, 50.15, 50.25], dtype=np.float32)
        lat.units = "degrees_north"
        lat.axis = "Y"

        precip = grid_grp.createVariable(
            "precipitation", "i2", ("time", "lon", "lat"), fill_value=-9999
        )
        precip.set_auto_maskandscale(False)
        precip[:] = np.arange(12, dtype=np.int16).reshape((1, 4, 3))
        precip.units = "mm/hr"
        precip.scale_factor = np.float32(0.1)

        qa = grid_grp.createVariable("probabilityLiquidPrecipitation", "u1", ("time", "lon", "lat"))
        qa.set_auto_maskandscale(False)
        qa[:] = np.ones((1, 4, 3), dtype=np.uint8)
        qa.flag_values = np.array([0, 1], dtype=np.uint8)
        qa.scale_factor = np.float32(0.5)

    asset = AssetReference("nc-1", nc_path.as_uri(), "netcdf", "application/x-netcdf")
    registry = ReaderRegistry((NetCDFReader(),))
    decoded = registry.read(asset, nc_path)

    assert decoded.crs == "EPSG:4326"
    assert decoded.grid is not None
    assert decoded.grid.width == 4 and decoded.grid.height == 3
    assert decoded.grid.resolution_x == pytest.approx(0.1, abs=1e-4)
    assert decoded.variables["Grid/precipitation"].dimensions == ("time", "lon", "lat")
    assert decoded.variables["Grid/precipitation"].scale_factor == pytest.approx(0.1)
    assert decoded.variables["Grid/precipitation"].nodata == -9999
    assert decoded.variables["Grid/probabilityLiquidPrecipitation"].semantics == "qa_flag"
    assert decoded.variables["Grid/probabilityLiquidPrecipitation"].scale_factor is None
    assert any("Dropped scaling" in w for w in decoded.warnings)
    assert isinstance(decoded.arrays["Grid/precipitation"], np.ndarray)
    assert decoded.arrays["Grid/precipitation"].dtype == np.int16


def test_netcdf_lazy_subset_unreferenced_and_corrupt_handling(tmp_path: Path) -> None:
    nc_path = tmp_path / "unref.nc"
    with netCDF4.Dataset(nc_path, mode="w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("x", 2)
        ds.createDimension("y", 2)
        v = ds.createVariable("soil", "f4", ("y", "x"))
        v[:] = np.ones((2, 2), dtype=np.float32)

    reader = NetCDFReader()
    decoded = reader.read(
        AssetReference("nc-2", nc_path.as_uri(), "netcdf", "application/x-netcdf"),
        nc_path,
        variables=("soil",),
    )
    assert decoded.crs is None
    assert decoded.grid is None
    assert list(decoded.variables.keys()) == ["soil"]
    assert any("No explicit CRS" in w for w in decoded.warnings)

    corrupt = tmp_path / "corrupt.nc"
    corrupt.write_bytes(b"CDF\x01broken_data")
    with pytest.raises(AssetDecodeError, match="Failed to decode NetCDF"):
        reader.read(
            AssetReference("bad", corrupt.as_uri(), "netcdf", "application/x-netcdf"), corrupt
        )
