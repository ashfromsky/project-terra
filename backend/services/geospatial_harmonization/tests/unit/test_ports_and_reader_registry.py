"""Unit tests for domain ports and ReaderRegistry format detection."""

from pathlib import Path

import pytest

from geospatial_harmonization import domain
from geospatial_harmonization.readers import (
    AssetDecodeError,
    ReaderRegistry,
    UnsupportedFormatError,
    detect_asset_format,
)


def _asset(
    uri: str, fmt: domain.DataFormat = "unknown", media: str = "application/octet-stream"
) -> domain.AssetReference:
    return domain.AssetReference("a1", uri, fmt, media)


class _StubReader:
    def __init__(self, fmt: domain.DataFormat) -> None:
        self._fmt = fmt

    @property
    def data_format(self) -> domain.DataFormat:
        return self._fmt

    def supports(self, asset: domain.AssetReference, header: bytes = b"") -> bool:
        return True

    def read(
        self, asset: domain.AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> domain.DecodedDataset:
        var = domain.VariableSpec("BAND1", "1", "float32", ("y", "x"), "continuous_intensive")
        return domain.DecodedDataset(asset, self._fmt, {"BAND1": var}, {"y": 1, "x": 1})


@pytest.mark.parametrize(
    ("filename", "payload", "expected"),
    [
        ("wrong.hdf", b"II*\x00" + b"\x00" * 16, "geotiff"),
        ("tile.bin", b"\x0e\x03\x13\x01" + b"\x00" * 16, "hdf4"),
        ("classic.dat", b"CDF\x01" + b"\x00" * 16, "netcdf"),
        ("smap.h5", b"\x89HDF\r\n\x1a\n" + b"\x00" * 16, "hdf5"),
        ("gpm.nc4", b"\x89HDF\r\n\x1a\n" + b"\x00" * 16, "netcdf"),
        ("resp.txt", b'\xef\xbb\xbf  \n  {"type": "FeatureCollection"}', "json"),
        ("fake.json", b"<!DOCTYPE html><html>Login</html>", "unknown"),
        ("blank.csv", b"   \n  ", "unknown"),
        ("obs.dat", b"lat,lon,t2m\n50.0,30.0,12.5\n", "csv"),
    ],
)
def test_detect_format_magic_and_guards(
    tmp_path: Path, filename: str, payload: bytes, expected: domain.DataFormat
) -> None:
    target = tmp_path / filename
    target.write_bytes(payload)
    assert detect_asset_format(_asset(f"local://{filename}"), path=target) == expected


def test_detect_format_zarr_directory(tmp_path: Path) -> None:
    zarr_dir = tmp_path / "store.zarr"
    zarr_dir.mkdir()
    assert detect_asset_format(_asset("local://store.zarr"), path=zarr_dir) == "unknown"
    (zarr_dir / "zarr.json").write_text("{}")
    assert detect_asset_format(_asset("local://store.zarr"), path=zarr_dir) == "zarr"


def test_registry_resolves_and_rejects_missing_empty_or_unsupported(tmp_path: Path) -> None:
    registry = ReaderRegistry((_StubReader("geotiff"),))
    assert registry.registered_formats() == ("geotiff",)
    resolved: domain.AssetReader = registry.resolve(_asset("local://a.tif"), header=b"II*\x00")
    assert resolved.data_format == "geotiff"

    tif = tmp_path / "ok.tif"
    tif.write_bytes(b"MM\x00*" + b"\x00" * 16)
    assert registry.read(_asset("local://ok.tif"), tif).data_format == "geotiff"

    empty = tmp_path / "empty.tif"
    empty.write_bytes(b"")
    with pytest.raises(AssetDecodeError, match="empty"):
        registry.read(_asset("local://empty.tif"), empty)
    with pytest.raises(AssetDecodeError, match="does not exist"):
        registry.read(_asset("local://missing.tif"), tmp_path / "missing.tif")

    hdf4 = tmp_path / "unreg.hdf"
    hdf4.write_bytes(b"\x0e\x03\x13\x01" + b"\x00" * 16)
    with pytest.raises(UnsupportedFormatError, match="hdf4"):
        registry.read(_asset("local://unreg.hdf"), hdf4)

    for port_name in (
        "DataHandler",
        "AssetReader",
        "GridTransformer",
        "StoragePort",
        "JobRepository",
        "DatasetRepository",
    ):
        assert hasattr(domain, port_name)
