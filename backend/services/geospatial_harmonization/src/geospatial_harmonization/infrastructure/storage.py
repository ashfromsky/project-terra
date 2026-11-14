"""StoragePort implementations for local filesystem and S3-compatible object stores."""

import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

import boto3

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.models.dataset import AssetReference, DataFormat
from geospatial_harmonization.domain.ports import StoragePort

_EXT_TO_FORMAT: dict[str, DataFormat] = {
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".nc": "netcdf",
    ".nc4": "netcdf",
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".hdf": "hdf4",
    ".zarr": "zarr",
    ".json": "json",
    ".csv": "csv",
}

_CHUNK_SIZE = 65536


def normalize_object_key(key: str) -> str:
    """Validate and normalize a relative POSIX object storage key against path traversal."""
    if not key or "\x00" in key or "\\" in key or key.startswith("/"):
        raise ValueError(f"Invalid object storage key: {key!r}")
    parts = key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe path segment in object storage key: {key!r}")
    return str(PurePosixPath(*parts))


def infer_data_format(key: str, media_type: str) -> DataFormat:
    """Infer canonical DataFormat from object key extension or MIME media type."""
    ext = PurePosixPath(key).suffix.lower()
    if ext in _EXT_TO_FORMAT:
        return _EXT_TO_FORMAT[ext]
    lower_mt = media_type.lower()
    if "tiff" in lower_mt:
        return "geotiff"
    if "netcdf" in lower_mt:
        return "netcdf"
    if "hdf5" in lower_mt:
        return "hdf5"
    if "json" in lower_mt:
        return "json"
    if "csv" in lower_mt:
        return "csv"
    return "unknown"


def _write_bytes_atomic(dest: Path, data: bytes) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".ghs-tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, dest)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return digest


def _copy_file_atomic(src: Path, dst: Path) -> tuple[str, int]:
    if not src.is_file():
        raise FileNotFoundError(f"Source file does not exist: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    total = 0
    fd, tmp_name = tempfile.mkstemp(dir=dst.parent, prefix=".ghs-tmp-")
    try:
        with src.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(_CHUNK_SIZE):
                hasher.update(chunk)
                writer.write(chunk)
                total += len(chunk)
        os.replace(tmp_name, dst)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return hasher.hexdigest(), total


class LocalObjectStore:
    """Filesystem StoragePort rooted under a fixed directory with atomic writes."""

    def __init__(self, root_dir: Path) -> None:
        self._root = root_dir.resolve()

    @property
    def root_dir(self) -> Path:
        return self._root

    def _resolve_path(self, key: str) -> tuple[str, Path]:
        norm = normalize_object_key(key)
        resolved = (self._root / norm).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"Key '{key}' escapes local storage root")
        return norm, resolved

    async def put_bytes(
        self, key: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> AssetReference:
        norm, dest = self._resolve_path(key)
        digest = await asyncio.to_thread(_write_bytes_atomic, dest, data)
        return AssetReference(
            asset_id=norm,
            uri=dest.as_uri(),
            data_format=infer_data_format(norm, media_type),
            media_type=media_type,
            checksum_sha256=digest,
            size_bytes=len(data),
        )

    async def put_file(
        self, key: str, path: Path, media_type: str = "application/octet-stream"
    ) -> AssetReference:
        norm, dest = self._resolve_path(key)
        digest, size = await asyncio.to_thread(_copy_file_atomic, path, dest)
        return AssetReference(
            asset_id=norm,
            uri=dest.as_uri(),
            data_format=infer_data_format(norm, media_type),
            media_type=media_type,
            checksum_sha256=digest,
            size_bytes=size,
        )

    async def get_bytes(self, key: str) -> bytes:
        _, target = self._resolve_path(key)

        def _read() -> bytes:
            if not target.is_file():
                raise FileNotFoundError(f"Object not found in local store: {key}")
            return target.read_bytes()

        return await asyncio.to_thread(_read)

    async def materialize_to_path(self, key: str, dest: Path) -> Path:
        _, src = self._resolve_path(key)

        def _copy() -> Path:
            if not src.is_file():
                raise FileNotFoundError(f"Object not found in local store: {key}")
            dest_resolved = dest.resolve()
            dest_resolved.parent.mkdir(parents=True, exist_ok=True)
            if dest_resolved != src:
                shutil.copy2(src, dest_resolved)
            return dest_resolved

        return await asyncio.to_thread(_copy)

    async def exists(self, key: str) -> bool:
        _, target = self._resolve_path(key)
        return await asyncio.to_thread(target.is_file)


class S3ClientProtocol(Protocol):
    """Minimal structural subset of a boto3 S3 client used by S3ObjectStore."""

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        err = response.get("Error")
        if isinstance(err, dict):
            return str(err.get("Code", "")) in ("404", "NoSuchKey", "NotFound")
    return isinstance(exc, FileNotFoundError)


def _read_s3_body(resp: dict[str, object]) -> bytes:
    body = resp.get("Body")
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    read_fn = getattr(body, "read", None)
    close_fn = getattr(body, "close", None)
    if not callable(read_fn):
        raise OSError("S3 get_object response missing readable Body stream")
    try:
        raw = read_fn()
        if not isinstance(raw, (bytes, bytearray)):
            raise OSError("S3 Body.read() did not return bytes")
        return bytes(raw)
    finally:
        if callable(close_fn):
            close_fn()


class S3ObjectStore:
    """S3-compatible StoragePort implementation via boto3 in worker threads."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        client: S3ClientProtocol | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket name must be non-empty")
        self._bucket = bucket.strip()
        clean_prefix = prefix.strip("/")
        self._prefix = normalize_object_key(clean_prefix) if clean_prefix else ""
        self._client: S3ClientProtocol = (
            client
            if client is not None
            else boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)
        )

    def _object_key(self, key: str) -> tuple[str, str]:
        norm = normalize_object_key(key)
        full = f"{self._prefix}/{norm}" if self._prefix else norm
        return norm, full

    async def put_bytes(
        self, key: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> AssetReference:
        norm, obj_key = self._object_key(key)
        digest = hashlib.sha256(data).hexdigest()
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=obj_key,
            Body=data,
            ContentType=media_type,
        )
        return AssetReference(
            asset_id=norm,
            uri=f"s3://{self._bucket}/{obj_key}",
            data_format=infer_data_format(norm, media_type),
            media_type=media_type,
            checksum_sha256=digest,
            size_bytes=len(data),
        )

    async def put_file(
        self, key: str, path: Path, media_type: str = "application/octet-stream"
    ) -> AssetReference:
        data = await asyncio.to_thread(path.read_bytes)
        return await self.put_bytes(key, data, media_type)

    async def get_bytes(self, key: str) -> bytes:
        _, obj_key = self._object_key(key)

        def _fetch() -> bytes:
            try:
                resp = self._client.get_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    raise FileNotFoundError(
                        f"Object not found in S3: s3://{self._bucket}/{obj_key}"
                    ) from exc
                raise
            return _read_s3_body(resp)

        return await asyncio.to_thread(_fetch)

    async def materialize_to_path(self, key: str, dest: Path) -> Path:
        data = await self.get_bytes(key)
        await asyncio.to_thread(_write_bytes_atomic, dest.resolve(), data)
        return dest.resolve()

    async def exists(self, key: str) -> bool:
        _, obj_key = self._object_key(key)

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    return False
                raise
            return True

        return await asyncio.to_thread(_head)


def build_storage_port(settings: Settings) -> StoragePort:
    """Instantiate configured StoragePort adapter from service Settings."""
    if settings.storage_backend == "local":
        return LocalObjectStore(settings.local_storage_dir)
    if not settings.s3_bucket:
        raise ValueError("s3_bucket must be configured when storage_backend='s3'")
    return S3ObjectStore(
        settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
    )
