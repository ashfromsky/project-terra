"""Format-agnostic reader subsystem exports."""

from geospatial_harmonization.readers.geotiff import GeoTIFFReader
from geospatial_harmonization.readers.hdf5 import HDF5Reader
from geospatial_harmonization.readers.netcdf import NetCDFReader
from geospatial_harmonization.readers.registry import (
    AssetDecodeError,
    ReaderRegistry,
    UnsupportedFormatError,
    detect_asset_format,
)
from geospatial_harmonization.readers.tabular import CSVReader, JSONReader
from geospatial_harmonization.readers.zarr import ZarrReader

__all__ = [
    "AssetDecodeError",
    "CSVReader",
    "GeoTIFFReader",
    "HDF5Reader",
    "JSONReader",
    "NetCDFReader",
    "ReaderRegistry",
    "UnsupportedFormatError",
    "ZarrReader",
    "detect_asset_format",
]
