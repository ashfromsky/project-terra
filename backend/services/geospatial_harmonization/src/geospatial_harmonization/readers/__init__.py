"""Format-agnostic reader subsystem exports."""

from geospatial_harmonization.readers.geotiff import GeoTIFFReader
from geospatial_harmonization.readers.hdf4 import HDF4Reader
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


def build_default_reader_registry() -> ReaderRegistry:
    """Create a ReaderRegistry wired with all seven supported geospatial readers."""
    return ReaderRegistry(
        (
            GeoTIFFReader(),
            NetCDFReader(),
            HDF5Reader(),
            HDF4Reader(),
            ZarrReader(),
            JSONReader(),
            CSVReader(),
        )
    )


__all__ = [
    "AssetDecodeError",
    "CSVReader",
    "GeoTIFFReader",
    "HDF4Reader",
    "HDF5Reader",
    "JSONReader",
    "NetCDFReader",
    "ReaderRegistry",
    "UnsupportedFormatError",
    "ZarrReader",
    "build_default_reader_registry",
    "detect_asset_format",
]
