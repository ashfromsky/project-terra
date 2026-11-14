"""Tests for LocalObjectStore, S3ObjectStore, streaming I/O, and cleanup helpers."""

import hashlib
import io
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import StorageIntegrityError
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


class _ChunkedBody:
    def __init__(self, payload: bytes) -> None:
        self._buf = io.BytesIO(payload)
        self.closed = False
        self.read_calls: list[int | None] = []

    def read(self, amt: int | None = None) -> bytes:
        self.read_calls.append(amt)
        return self._buf.read() if amt is None else self._buf.read(amt)

    def close(self) -> None:
        self.closed = True


class _FakeS3Client:
    def __init__(self, *, fail_part_number: int | None = None) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str, datetime]] = {}
        self.multipart_uploads: dict[str, dict[str, Any]] = {}
        self.aborted_uploads: list[tuple[str, str, str]] = []
        self.fail_part_number = fail_part_number
        self._seq = 0

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, object]:
        self.objects[(Bucket, Key)] = (Body, ContentType, datetime.now(UTC))
        return {"ETag": '"mock"'}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError("NoSuchKey")
        data, content_type, _ = self.objects[(Bucket, Key)]
        return {"Body": _ChunkedBody(data), "ContentType": content_type}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError("404")
        data, content_type, modified = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(data),
            "ContentType": content_type,
            "LastModified": modified,
            "ETag": '"mock"',
        }

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix", ""))
        matching = sorted(
            (key, data, modified)
            for (b, key), (data, _, modified) in self.objects.items()
            if b == bucket and key.startswith(prefix)
        )
        max_keys = int(kwargs.get("MaxKeys", 2))
        start = int(kwargs.get("ContinuationToken", 0) or 0)
        page = matching[start : start + max_keys]
        is_truncated = (start + max_keys) < len(matching)
        return {
            "Contents": [
                {"Key": key, "Size": len(data), "LastModified": modified, "ETag": '"mock"'}
                for key, data, modified in page
            ],
            "IsTruncated": is_truncated,
            "NextContinuationToken": str(start + max_keys) if is_truncated else None,
        }

    def create_multipart_upload(
        self, *, Bucket: str, Key: str, ContentType: str
    ) -> dict[str, object]:
        self._seq += 1
        uid = f"upload-{self._seq}"
        self.multipart_uploads[uid] = {
            "Bucket": Bucket,
            "Key": Key,
            "ContentType": ContentType,
            "UploadId": uid,
            "Initiated": datetime.now(UTC),
            "Parts": {},
        }
        return {"UploadId": uid}

    def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> dict[str, object]:
        _ = (Bucket, Key)
        if self.fail_part_number == PartNumber:
            raise OSError("Simulated upload part failure")
        self.multipart_uploads[UploadId]["Parts"][PartNumber] = Body
        return {"ETag": f'"part-{PartNumber}"'}

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, object],
    ) -> dict[str, object]:
        _ = MultipartUpload
        entry = self.multipart_uploads.pop(UploadId)
        parts = entry["Parts"]
        merged = b"".join(parts[idx] for idx in sorted(parts))
        self.objects[(Bucket, Key)] = (merged, str(entry["ContentType"]), datetime.now(UTC))
        return {"ETag": '"mp-complete"'}

    def list_multipart_uploads(self, **kwargs: Any) -> dict[str, Any]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix", ""))
        uploads = [
            {
                "Key": entry["Key"],
                "UploadId": entry["UploadId"],
                "Initiated": entry["Initiated"],
            }
            for entry in self.multipart_uploads.values()
            if entry["Bucket"] == bucket and str(entry["Key"]).startswith(prefix)
        ]
        return {"Uploads": uploads, "IsTruncated": False}

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> dict[str, object]:
        self.aborted_uploads.append((Bucket, Key, UploadId))
        self.multipart_uploads.pop(UploadId, None)
        return {}


async def test_local_object_store_lifecycle_streaming_and_cleanup(tmp_path: Path) -> None:
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
    payload = b"tif-stream-chunk-" * 40
    expected_sha = hashlib.sha256(payload).hexdigest()
    src_tif.write_bytes(payload)
    stream_info = await store.put_file_stream(
        "derived/ds1/out.tif",
        src_tif,
        media_type="image/tiff",
        chunk_size=64,
        verify_sha256=expected_sha,
    )
    assert stream_info.key == "derived/ds1/out.tif"
    assert stream_info.size_bytes == len(payload)
    assert stream_info.checksum_sha256 == expected_sha

    with pytest.raises(StorageIntegrityError, match="SHA-256"):
        await store.put_file_stream("derived/ds1/bad.tif", src_tif, verify_sha256="0" * 64)
    assert await store.exists("derived/ds1/bad.tif") is False

    mat = await store.stream_to_path(
        "derived/ds1/out.tif", tmp_path / "work" / "out.tif", chunk_size=32
    )
    assert mat.read_bytes() == payload

    head = await store.head_object("derived/ds1/out.tif")
    assert head is not None and head.size_bytes == len(payload)
    assert await store.head_object("missing/none.tif") is None

    abandoned = tmp_path / "store" / "intermediate" / ".ghs-tmp-old"
    abandoned.parent.mkdir(parents=True, exist_ok=True)
    abandoned.write_bytes(b"stale")
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(abandoned, (old_ts, old_ts))
    fresh_tmp = tmp_path / "store" / "intermediate" / ".ghs-tmp-fresh"
    fresh_tmp.write_bytes(b"fresh")

    listed = await store.list_objects()
    assert [item.key for item in listed] == ["derived/ds1/out.tif", "raw/ds1/sample.nc"]
    assert [item.key for item in await store.list_objects("derived/")] == ["derived/ds1/out.tif"]

    assert await store.cleanup_abandoned_temp_files(older_than_seconds=1800) == 1
    assert not abandoned.exists()
    assert fresh_tmp.exists()

    assert await store.delete_object("derived/ds1/out.tif") is True
    assert await store.delete_object("derived/ds1/out.tif") is False

    assert await store.exists("missing/object.bin") is False
    with pytest.raises(FileNotFoundError):
        await store.get_bytes("missing/object.bin")

    for bad_key in ("../escape.txt", "/etc/passwd", "raw//bad.txt", r"raw\bad.txt"):
        with pytest.raises(ValueError):
            await store.put_bytes(bad_key, b"x")


async def test_s3_object_store_streaming_multipart_pagination_and_cleanup(
    tmp_path: Path,
) -> None:
    fake = _FakeS3Client()
    s3 = S3ObjectStore(
        "terra-bucket",
        prefix="ghs/prod",
        client=fake,
        multipart_threshold_bytes=64,
        temp_dirs=(tmp_path / "worktemp",),
    )
    assert await s3.exists("derived/a/ndvi.tif") is False

    ref = await s3.put_bytes("derived/a/ndvi.tif", b"geotiff-data", media_type="image/tiff")
    assert ref.uri == "s3://terra-bucket/ghs/prod/derived/a/ndvi.tif"
    assert ref.data_format == "geotiff"

    big_src = tmp_path / "big.tif"
    big_payload = b"ABCD1234" * 30
    big_sha = hashlib.sha256(big_payload).hexdigest()
    big_src.write_bytes(big_payload)
    mp_info = await s3.put_file_stream(
        "derived/a/big.tif",
        big_src,
        media_type="image/tiff",
        chunk_size=64,
        verify_sha256=big_sha,
    )
    assert mp_info.size_bytes == len(big_payload)
    assert mp_info.checksum_sha256 == big_sha

    await s3.put_bytes("raw/modis/tile.hdf", b"raw-hdf")
    listed_all = await s3.list_objects()
    assert [obj.key for obj in listed_all] == [
        "derived/a/big.tif",
        "derived/a/ndvi.tif",
        "raw/modis/tile.hdf",
    ]
    assert [obj.key for obj in await s3.list_objects("raw/")] == ["raw/modis/tile.hdf"]

    local_dest = await s3.stream_to_path(
        "derived/a/big.tif", tmp_path / "m" / "big.tif", chunk_size=50
    )
    assert local_dest.read_bytes() == big_payload

    assert await s3.delete_object("derived/a/ndvi.tif") is True
    assert await s3.delete_object("derived/a/ndvi.tif") is False

    stale_uid = "stale-upload-1"
    fake.multipart_uploads[stale_uid] = {
        "Bucket": "terra-bucket",
        "Key": "ghs/prod/intermediate/fail.tif",
        "UploadId": stale_uid,
        "Initiated": datetime.now(UTC) - timedelta(hours=3),
    }
    fresh_uid = "fresh-upload-2"
    fake.multipart_uploads[fresh_uid] = {
        "Bucket": "terra-bucket",
        "Key": "ghs/prod/intermediate/live.tif",
        "UploadId": fresh_uid,
        "Initiated": datetime.now(UTC),
    }
    assert await s3.abort_incomplete_multipart_uploads(older_than_seconds=3600) == 1
    assert fresh_uid in fake.multipart_uploads
    assert stale_uid not in fake.multipart_uploads

    failing_client = _FakeS3Client(fail_part_number=2)
    failing_s3 = S3ObjectStore(
        "terra-bucket",
        prefix="ghs/prod",
        client=failing_client,
        multipart_threshold_bytes=64,
    )
    with pytest.raises(OSError, match="Simulated upload part failure"):
        await failing_s3.put_file_stream("intermediate/bad.tif", big_src, chunk_size=64)
    assert len(failing_client.aborted_uploads) == 1

    with pytest.raises(FileNotFoundError):
        await s3.get_bytes("derived/a/missing.tif")

    local_port = build_storage_port(
        Settings(storage_backend="local", local_storage_dir=tmp_path / "cfg-local")
    )
    assert isinstance(local_port, LocalObjectStore)
    with pytest.raises(ValueError, match="s3_bucket"):
        build_storage_port(Settings(storage_backend="s3", s3_bucket=None))
