"""Tests for LocalObjectStore, S3ObjectStore, and storage key validation."""

import io
from pathlib import Path

import pytest

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.ports import StoragePort
from geospatial_harmonization.infrastructure.storage import (
    LocalObjectStore,
    S3ObjectStore,
    build_storage_port,
)


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response: dict[str, object] = {"Error": {"Code": code}}


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, object]:
        self.objects[(Bucket, Key)] = (Body, ContentType)
        return {"ETag": "mock"}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError("NoSuchKey")
        data, content_type = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(data), "ContentType": content_type}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError("404")
        return {"ContentLength": len(self.objects[(Bucket, Key)][0])}


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


async def test_s3_object_store_round_trip_and_factory(tmp_path: Path) -> None:
    fake = _FakeS3Client()
    s3: StoragePort = S3ObjectStore("terra-bucket", prefix="ghs/prod", client=fake)
    assert await s3.exists("derived/a/ndvi.tif") is False

    ref = await s3.put_bytes("derived/a/ndvi.tif", b"geotiff-data", media_type="image/tiff")
    assert ref.uri == "s3://terra-bucket/ghs/prod/derived/a/ndvi.tif"
    assert ref.data_format == "geotiff"
    assert await s3.exists("derived/a/ndvi.tif") is True
    assert await s3.get_bytes("derived/a/ndvi.tif") == b"geotiff-data"

    local_dest = await s3.materialize_to_path("derived/a/ndvi.tif", tmp_path / "m" / "ndvi.tif")
    assert local_dest.read_bytes() == b"geotiff-data"

    with pytest.raises(FileNotFoundError):
        await s3.get_bytes("derived/a/missing.tif")

    local_port = build_storage_port(
        Settings(storage_backend="local", local_storage_dir=tmp_path / "cfg-local")
    )
    assert isinstance(local_port, LocalObjectStore)
    with pytest.raises(ValueError, match="s3_bucket"):
        build_storage_port(Settings(storage_backend="s3", s3_bucket=None))
