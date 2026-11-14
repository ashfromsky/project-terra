"""Runtime smoke tests for geospatial format backends and CRS libraries."""

import h5py
import netCDF4
import pyproj
import rasterio
import rioxarray
import shapely
import xarray
import zarr
from pyhdf.SD import SD


def test_geospatial_dependencies_import_and_expose_expected_drivers() -> None:
    assert callable(SD)
    assert h5py.__version__
    assert netCDF4.__version__
    assert zarr.__version__
    assert xarray.__version__
    assert rioxarray.__version__
    assert shapely.__version__

    sinusoidal = pyproj.CRS.from_user_input(
        "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
    )
    ease2 = pyproj.CRS.from_epsg(6933)
    assert sinusoidal.is_projected
    assert ease2.is_projected

    with rasterio.Env() as env:
        drivers = env.drivers()
    assert {"GTiff", "netCDF", "HDF5"}.issubset(drivers)
