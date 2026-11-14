"""Tests for LocalObjectStore and storage key validation."""

from pathlib import Path

import pytest

from geospatial_harmonization.domain.ports import StoragePort
from geospatial_harmonization.infrastructure.storage import LocalObjectStore


async def test_local_object_store_lifecycle_and_traversal_guards(tmp_path: Path) -> None:
    store: StoragePort = LocalObjectStore(tmp_path / "store")
    ref = await store.put_bytes(
        "raw/ds1/sample.nc", b"nc-payload", media_type="application/x-netcdf"
    )
    assert ref.asset_id == "raw/ds1/sample.nc"
    assert ref.data_format == "netcdf"
    assert ref.size_bytes == 10
    assert ref.checksum_sha256 is not None and len(ref.checksum_sha256) == 64
    assert await store.exists("raw/ds1/sample.nc") is True
    assert await store.get_bytes("raw/ds1/sample.nc") == b"nc-payload"

    src_tif = tmp_path / "src.tif"
    src_tif.write_bytes(b"tif-bytes")
    tif_ref = await store.put_file("derived/ds1/out.tif", src_tif, media_type="image/tiff")
    assert tif_ref.data_format == "geotiff"

    mat = await store.materialize_to_path("derived/ds1/out.tif", tmp_path / "work" / "out.tif")
    assert mat.read_bytes() == b"tif-bytes"

    assert await store.exists("missing/object.bin") is False
    with pytest.raises(FileNotFoundError):
        await store.get_bytes("missing/object.bin")

    for bad_key in ("../escape.txt", "/etc/passwd", "raw//bad.txt", r"raw\bad.txt"):
        with pytest.raises(ValueError):
            await store.put_bytes(bad_key, b"x")
