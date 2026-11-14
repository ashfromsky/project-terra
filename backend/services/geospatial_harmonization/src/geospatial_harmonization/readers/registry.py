"""Format detection and ReaderRegistry dispatch without provider coupling."""

from pathlib import Path
from urllib.parse import urlparse

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
)
from geospatial_harmonization.domain.ports import AssetReader

_HDF4_MAGIC = b"\x0e\x03\x13\x01"
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
_NETCDF_CLASSIC_MAGIC = (b"CDF\x01", b"CDF\x02", b"CDF\x05")
_TIFF_MAGIC = (b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b")

_EXT_GROUPS: tuple[tuple[tuple[str, ...], DataFormat], ...] = (
    ((".hdf", ".hdf4", ".h4"), "hdf4"),
    ((".h5", ".hdf5", ".he5"), "hdf5"),
    ((".nc", ".nc4", ".cdf", ".netcdf"), "netcdf"),
    ((".tif", ".tiff", ".geotiff"), "geotiff"),
    ((".zarr",), "zarr"),
    ((".json", ".geojson"), "json"),
    ((".csv",), "csv"),
)
_EXT_MAP: dict[str, DataFormat] = {ext: fmt for exts, fmt in _EXT_GROUPS for ext in exts}
_MEDIA_TOKENS: tuple[tuple[str, DataFormat], ...] = (
    ("json", "json"),
    ("csv", "csv"),
    ("tiff", "geotiff"),
)

_TEXT_FORMATS: frozenset[DataFormat] = frozenset({"json", "csv"})


class UnsupportedFormatError(IncompatibleDatasetError):
    """Raised when an asset format cannot be detected or has no registered reader."""


class AssetDecodeError(IncompatibleDatasetError):
    """Raised when a readable asset is missing, empty, truncated, or corrupt."""


def _suffix_from(asset: AssetReference, path: Path | None) -> str:
    if path is not None and path.suffix:
        return path.suffix.lower()
    return Path(urlparse(asset.uri).path).suffix.lower()


def _detect_text_prefix(header: bytes) -> str | None:
    if not header or b"\x00" in header:
        return None
    try:
        text = header.lstrip(b"\xef\xbb\xbf").decode("utf-8", errors="strict").lstrip()
    except UnicodeDecodeError:
        return None
    return text


def detect_asset_format(
    asset: AssetReference, path: Path | None = None, header: bytes | None = None
) -> DataFormat:
    """Detect data format from Zarr store markers, magic bytes, and extension fallbacks."""
    if path is not None and path.is_dir():
        zarr_markers = ("zarr.json", ".zgroup", ".zarray")
        return "zarr" if any((path / marker).exists() for marker in zarr_markers) else "unknown"

    raw = header
    if raw is None and path is not None and path.is_file():
        with path.open("rb") as handle:
            raw = handle.read(256)

    ext = _suffix_from(asset, path)
    if raw:
        if raw.startswith(_HDF4_MAGIC):
            return "hdf4"
        if raw.startswith(_TIFF_MAGIC):
            return "geotiff"
        if raw.startswith(_NETCDF_CLASSIC_MAGIC):
            return "netcdf"
        if raw.startswith(_HDF5_MAGIC):
            if ext in {".nc", ".nc4", ".cdf", ".netcdf"} or asset.data_format == "netcdf":
                return "netcdf"
            return "hdf5"
        if raw.startswith(b"PK\x03\x04") and (ext == ".zarr" or ".zarr.zip" in asset.uri.lower()):
            return "zarr"

        text = _detect_text_prefix(raw)
        if text is not None:
            if not text or text.startswith("<"):
                return "unknown"
            if text.startswith(("{", "[")):
                return "json"
            lines = text.splitlines()
            if ext == ".csv" or (len(lines) > 1 and "," in lines[0]):
                return "csv"
        elif ext in _EXT_MAP and _EXT_MAP[ext] in _TEXT_FORMATS:
            return "unknown"

    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    media = asset.media_type.lower()
    for token, fmt in _MEDIA_TOKENS:
        if token in media:
            return fmt
    return asset.data_format


class ReaderRegistry:
    """Registry mapping detected DataFormats to format-specific AssetReader instances."""

    def __init__(self, readers: tuple[AssetReader, ...] = ()) -> None:
        self._readers: dict[DataFormat, AssetReader] = {}
        for reader in readers:
            self.register(reader)

    def register(self, reader: AssetReader) -> None:
        self._readers[reader.data_format] = reader

    def registered_formats(self) -> tuple[DataFormat, ...]:
        return tuple(self._readers.keys())

    def resolve(
        self, asset: AssetReference, path: Path | None = None, header: bytes = b""
    ) -> AssetReader:
        detected = detect_asset_format(asset, path=path, header=header or None)
        if detected != "unknown":
            reader = self._readers.get(detected)
            if reader is not None and reader.supports(asset, header=header):
                return reader
            raise UnsupportedFormatError(
                f"No reader registered for detected format '{detected}' (asset='{asset.asset_id}')"
            )
        for reader in self._readers.values():
            if reader.supports(asset, header=header):
                return reader
        raise UnsupportedFormatError(f"Unsupported format for asset '{asset.asset_id}'")

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        if not path.exists():
            raise AssetDecodeError(f"Asset path does not exist: {path}")
        header = b""
        if path.is_file():
            if path.stat().st_size == 0:
                raise AssetDecodeError(f"Asset file is empty: {path}")
            with path.open("rb") as handle:
                header = handle.read(256)
        reader = self.resolve(asset, path=path, header=header)
        return reader.read(asset, path, variables=variables)
