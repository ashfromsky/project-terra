"""StoragePort implementations for local filesystem and S3-compatible object stores."""

import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import boto3
from botocore.config import Config as BotoConfig

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import StorageIntegrityError
from geospatial_harmonization.domain.models.dataset import AssetReference, DataFormat
from geospatial_harmonization.domain.models.storage import StoredObjectInfo
from geospatial_harmonization.domain.ports import StoragePort

logger = logging.getLogger(__name__)


def normalize_s3_endpoint_url(endpoint_url: str | None, bucket: str | None = None) -> str | None:
    """Normalize custom S3/R2 endpoint URL and strip accidental trailing bucket path."""
    if endpoint_url is None:
        return None
    cleaned = endpoint_url.strip().rstrip("/")
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    path = parsed.path.rstrip("/")
    if bucket and path == f"/{bucket.strip()}":
        logger.warning(
            "Stripping trailing bucket segment '/%s' from s3_endpoint_url; "
            "configure S3_ENDPOINT_URL without the bucket path.",
            bucket.strip(),
        )
        path = ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


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

_DEFAULT_CHUNK_SIZE = 1_048_576
_MULTIPART_MIN_PART_SIZE = 5 * 1024 * 1024
_TEMP_PREFIX = ".ghs-tmp-"


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
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=_TEMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, dest)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return digest


def _compute_file_sha256_and_size(
    src: Path, chunk_size: int = _DEFAULT_CHUNK_SIZE
) -> tuple[str, int]:
    if not src.is_file():
        raise FileNotFoundError(f"Source file does not exist: {src}")
    hasher = hashlib.sha256()
    total = 0
    with src.open("rb") as reader:
        while chunk := reader.read(chunk_size):
            hasher.update(chunk)
            total += len(chunk)
    return hasher.hexdigest(), total


def _copy_file_atomic(
    src: Path,
    dst: Path,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    expected_sha256: str | None = None,
) -> tuple[str, int]:
    if not src.is_file():
        raise FileNotFoundError(f"Source file does not exist: {src}")
    dst_resolved = dst.resolve()
    dst_resolved.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst_resolved:
        digest, total = _compute_file_sha256_and_size(src, chunk_size)
        if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
            raise StorageIntegrityError(
                f"SHA-256 mismatch for '{src}': expected {expected_sha256}, got {digest}"
            )
        return digest, total
    hasher = hashlib.sha256()
    total = 0
    fd, tmp_name = tempfile.mkstemp(dir=dst_resolved.parent, prefix=_TEMP_PREFIX)
    try:
        with src.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(chunk_size):
                hasher.update(chunk)
                writer.write(chunk)
                total += len(chunk)
        digest = hasher.hexdigest()
        if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
            raise StorageIntegrityError(
                f"SHA-256 mismatch for '{src}': expected {expected_sha256}, got {digest}"
            )
        os.replace(tmp_name, dst_resolved)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return digest, total


def _write_stream_atomic(
    dest: Path,
    chunk_reader: Callable[[], bytes],
) -> tuple[str, int]:
    dest_resolved = dest.resolve()
    dest_resolved.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    total = 0
    fd, tmp_name = tempfile.mkstemp(dir=dest_resolved.parent, prefix=_TEMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as writer:
            while True:
                chunk = chunk_reader()
                if not chunk:
                    break
                hasher.update(chunk)
                writer.write(chunk)
                total += len(chunk)
        os.replace(tmp_name, dest_resolved)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return hasher.hexdigest(), total


def _cleanup_abandoned_in_dirs(dirs: tuple[Path, ...], *, older_than_seconds: int) -> int:
    if older_than_seconds < 0:
        raise ValueError("older_than_seconds must be >= 0")
    cutoff = datetime.now(UTC).timestamp() - older_than_seconds
    removed = 0
    seen: set[Path] = set()
    for directory in dirs:
        if not directory.is_dir():
            continue
        for candidate in directory.rglob(f"{_TEMP_PREFIX}*"):
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            try:
                if candidate.stat().st_mtime <= cutoff:
                    candidate.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed


def _prune_empty_parents(start: Path, stop_root: Path) -> None:
    current = start
    while current != stop_root and current.is_relative_to(stop_root):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


class LocalObjectStore:
    """Filesystem StoragePort rooted under a fixed directory with atomic writes."""

    def __init__(self, root_dir: Path, *, temp_dirs: tuple[Path, ...] = ()) -> None:
        self._root = root_dir.resolve()
        self._temp_dirs = tuple(d.resolve() for d in temp_dirs)

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
        info = await self.put_file_stream(key, path, media_type=media_type)
        _, dest = self._resolve_path(info.key)
        return AssetReference(
            asset_id=info.key,
            uri=dest.as_uri(),
            data_format=infer_data_format(info.key, media_type),
            media_type=media_type,
            checksum_sha256=info.checksum_sha256,
            size_bytes=info.size_bytes,
        )

    async def put_file_stream(
        self,
        key: str,
        source_path: Path,
        *,
        media_type: str = "application/octet-stream",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        verify_sha256: str | None = None,
    ) -> StoredObjectInfo:
        norm, dest = self._resolve_path(key)
        digest, size = await asyncio.to_thread(
            _copy_file_atomic,
            source_path,
            dest,
            chunk_size=chunk_size,
            expected_sha256=verify_sha256,
        )
        stat = await asyncio.to_thread(dest.stat)
        return StoredObjectInfo(
            key=norm,
            size_bytes=size,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            media_type=media_type,
            checksum_sha256=digest,
        )

    async def get_bytes(self, key: str) -> bytes:
        _, target = self._resolve_path(key)

        def _read() -> bytes:
            if not target.is_file():
                raise FileNotFoundError(f"Object not found in local store: {key}")
            return target.read_bytes()

        return await asyncio.to_thread(_read)

    async def materialize_to_path(self, key: str, dest: Path) -> Path:
        return await self.stream_to_path(key, dest)

    async def stream_to_path(
        self, key: str, destination_path: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE
    ) -> Path:
        _, src = self._resolve_path(key)
        await asyncio.to_thread(_copy_file_atomic, src, destination_path, chunk_size=chunk_size)
        return destination_path.resolve()

    async def exists(self, key: str) -> bool:
        _, target = self._resolve_path(key)
        return await asyncio.to_thread(target.is_file)

    async def head_object(self, key: str) -> StoredObjectInfo | None:
        norm, target = self._resolve_path(key)

        def _stat() -> StoredObjectInfo | None:
            if not target.is_file():
                return None
            stat = target.stat()
            return StoredObjectInfo(
                key=norm,
                size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )

        return await asyncio.to_thread(_stat)

    async def list_objects(self, prefix: str = "") -> list[StoredObjectInfo]:
        clean = normalize_object_key(prefix.rstrip("/")) if prefix.strip("/") else ""
        base = self._root / clean if clean else self._root

        def _scan() -> list[StoredObjectInfo]:
            if not base.exists():
                return []
            if base.is_file():
                stat = base.stat()
                return [
                    StoredObjectInfo(
                        key=clean,
                        size_bytes=stat.st_size,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                ]
            items: list[StoredObjectInfo] = []
            for entry in sorted(base.rglob("*")):
                if not entry.is_file() or entry.name.startswith(_TEMP_PREFIX):
                    continue
                stat = entry.stat()
                rel = entry.relative_to(self._root).as_posix()
                items.append(
                    StoredObjectInfo(
                        key=rel,
                        size_bytes=stat.st_size,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )
            return items

        return await asyncio.to_thread(_scan)

    async def delete_object(self, key: str) -> bool:
        _, target = self._resolve_path(key)

        def _delete() -> bool:
            if not target.is_file():
                return False
            target.unlink()
            _prune_empty_parents(target.parent, self._root)
            return True

        return await asyncio.to_thread(_delete)

    async def abort_incomplete_multipart_uploads(self, *, older_than_seconds: int = 3600) -> int:
        _ = older_than_seconds
        return 0

    async def cleanup_abandoned_temp_files(self, *, older_than_seconds: int = 1800) -> int:
        dirs = (self._root, *self._temp_dirs)
        return await asyncio.to_thread(
            _cleanup_abandoned_in_dirs, dirs, older_than_seconds=older_than_seconds
        )

    async def check_health(self) -> bool:
        """Verify local storage root exists and is writable."""

        def _probe() -> bool:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self._root, prefix=".health-", delete=True):
                    return True
            except OSError:
                return False

        return await asyncio.to_thread(_probe)

    async def generate_presigned_download_url(
        self,
        key: str,
        *,
        expires_in: int = 300,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> str | None:
        """Local filesystem store does not issue remote presigned URLs."""
        _ = (key, expires_in, filename, media_type)
        return None


class S3ClientProtocol(Protocol):
    """Minimal structural subset of a boto3 S3 client used by S3ObjectStore."""

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> dict[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...

    def list_multipart_uploads(self, **kwargs: Any) -> dict[str, Any]: ...

    def abort_multipart_upload(
        self, *, Bucket: str, Key: str, UploadId: str
    ) -> dict[str, object]: ...


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


def _stream_s3_body_to_file(resp: dict[str, object], dest: Path, chunk_size: int) -> None:
    body = resp.get("Body")
    if isinstance(body, (bytes, bytearray)):
        _write_bytes_atomic(dest.resolve(), bytes(body))
        return
    read_fn = getattr(body, "read", None)
    close_fn = getattr(body, "close", None)
    if not callable(read_fn):
        raise OSError("S3 get_object response missing readable Body stream")
    done_single_read = False

    def _next_chunk() -> bytes:
        nonlocal done_single_read
        if done_single_read:
            return b""
        try:
            raw = read_fn(chunk_size)
        except TypeError:
            done_single_read = True
            raw = read_fn()
        if raw is None:
            return b""
        if not isinstance(raw, (bytes, bytearray)):
            raise OSError("S3 Body.read() did not return bytes")
        return bytes(raw)

    try:
        _write_stream_atomic(dest, _next_chunk)
    finally:
        if callable(close_fn):
            close_fn()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_stored_info_from_head(norm_key: str, head: dict[str, object]) -> StoredObjectInfo:
    raw_size = head.get("ContentLength", 0)
    size = int(raw_size) if isinstance(raw_size, int) else 0
    etag = head.get("ETag")
    content_type = head.get("ContentType")
    return StoredObjectInfo(
        key=norm_key,
        size_bytes=size,
        last_modified=_parse_datetime(head.get("LastModified")),
        etag=str(etag).strip('"') if isinstance(etag, str) else None,
        media_type=str(content_type) if isinstance(content_type, str) else None,
    )


class S3ObjectStore:
    """S3-compatible StoragePort implementation via boto3 in worker threads."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        client: S3ClientProtocol | None = None,
        temp_dirs: tuple[Path, ...] = (),
        multipart_threshold_bytes: int = _MULTIPART_MIN_PART_SIZE,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket name must be non-empty")
        self._bucket = bucket.strip()
        clean_prefix = prefix.strip("/")
        self._prefix = normalize_object_key(clean_prefix) if clean_prefix else ""
        normalized_endpoint = normalize_s3_endpoint_url(endpoint_url, self._bucket)
        self._endpoint_url = normalized_endpoint
        self._region_name = (region_name or "auto").strip() or "auto"
        if client is not None:
            self._client = client
        else:
            boto_cfg = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": max(1, max_attempts), "mode": "standard"},
                connect_timeout=max(1.0, connect_timeout_seconds),
                read_timeout=max(1.0, read_timeout_seconds),
            )
            client_kwargs: dict[str, Any] = {
                "endpoint_url": normalized_endpoint,
                "region_name": self._region_name,
                "config": boto_cfg,
            }
            if aws_access_key_id:
                client_kwargs["aws_access_key_id"] = aws_access_key_id
            if aws_secret_access_key:
                client_kwargs["aws_secret_access_key"] = aws_secret_access_key
            self._client = boto3.client("s3", **client_kwargs)
        self._temp_dirs = tuple(d.resolve() for d in temp_dirs)
        self._multipart_threshold = max(1, multipart_threshold_bytes)

    def _object_key(self, key: str) -> tuple[str, str]:
        norm = normalize_object_key(key)
        full = f"{self._prefix}/{norm}" if self._prefix else norm
        return norm, full

    def _strip_prefix(self, full_key: str) -> str | None:
        if not self._prefix:
            return full_key
        expected = f"{self._prefix}/"
        if not full_key.startswith(expected):
            return None
        return full_key[len(expected) :]

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
        info = await self.put_file_stream(key, path, media_type=media_type)
        _, obj_key = self._object_key(info.key)
        return AssetReference(
            asset_id=info.key,
            uri=f"s3://{self._bucket}/{obj_key}",
            data_format=infer_data_format(info.key, media_type),
            media_type=media_type,
            checksum_sha256=info.checksum_sha256,
            size_bytes=info.size_bytes,
        )

    def _upload_stream_sync(
        self,
        obj_key: str,
        source_path: Path,
        media_type: str,
        total_size: int,
        chunk_size: int,
    ) -> None:
        create_mp = getattr(self._client, "create_multipart_upload", None)
        upload_part = getattr(self._client, "upload_part", None)
        complete_mp = getattr(self._client, "complete_multipart_upload", None)
        abort_mp = getattr(self._client, "abort_multipart_upload", None)
        if (
            total_size > self._multipart_threshold
            and callable(create_mp)
            and callable(upload_part)
            and callable(complete_mp)
            and callable(abort_mp)
        ):
            part_size = max(chunk_size, self._multipart_threshold)
            resp = cast(
                "dict[str, Any]",
                create_mp(Bucket=self._bucket, Key=obj_key, ContentType=media_type),
            )
            upload_id = str(resp["UploadId"])
            parts: list[dict[str, object]] = []
            try:
                with source_path.open("rb") as reader:
                    part_number = 1
                    while part_data := reader.read(part_size):
                        part_resp = cast(
                            "dict[str, Any]",
                            upload_part(
                                Bucket=self._bucket,
                                Key=obj_key,
                                PartNumber=part_number,
                                UploadId=upload_id,
                                Body=part_data,
                            ),
                        )
                        parts.append({"ETag": part_resp["ETag"], "PartNumber": part_number})
                        part_number += 1
                complete_mp(
                    Bucket=self._bucket,
                    Key=obj_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
                return
            except BaseException:
                with suppress(Exception):
                    abort_mp(Bucket=self._bucket, Key=obj_key, UploadId=upload_id)
                raise

        upload_fileobj = getattr(self._client, "upload_fileobj", None)
        if callable(upload_fileobj):
            with source_path.open("rb") as handle:
                upload_fileobj(
                    handle,
                    self._bucket,
                    obj_key,
                    ExtraArgs={"ContentType": media_type},
                )
            return

        self._client.put_object(
            Bucket=self._bucket,
            Key=obj_key,
            Body=source_path.read_bytes(),
            ContentType=media_type,
        )

    async def put_file_stream(
        self,
        key: str,
        source_path: Path,
        *,
        media_type: str = "application/octet-stream",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        verify_sha256: str | None = None,
    ) -> StoredObjectInfo:
        norm, obj_key = self._object_key(key)
        digest, total_size = await asyncio.to_thread(
            _compute_file_sha256_and_size, source_path, chunk_size
        )
        if verify_sha256 is not None and digest.lower() != verify_sha256.lower():
            raise StorageIntegrityError(
                f"SHA-256 mismatch before upload for '{norm}': "
                f"expected {verify_sha256}, got {digest}"
            )
        await asyncio.to_thread(
            self._upload_stream_sync, obj_key, source_path, media_type, total_size, chunk_size
        )
        head = await self.head_object(norm)
        if head is None:
            raise StorageIntegrityError(f"Post-upload verification failed: '{norm}' missing in S3")
        if head.size_bytes != total_size:
            raise StorageIntegrityError(
                f"Post-upload size mismatch for '{norm}': "
                f"expected {total_size}, got {head.size_bytes}"
            )
        return StoredObjectInfo(
            key=norm,
            size_bytes=total_size,
            last_modified=head.last_modified,
            etag=head.etag,
            media_type=media_type,
            checksum_sha256=digest,
        )

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
        return await self.stream_to_path(key, dest)

    async def stream_to_path(
        self, key: str, destination_path: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE
    ) -> Path:
        _, obj_key = self._object_key(key)

        def _download() -> Path:
            try:
                resp = self._client.get_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    raise FileNotFoundError(
                        f"Object not found in S3: s3://{self._bucket}/{obj_key}"
                    ) from exc
                raise
            resolved = destination_path.resolve()
            _stream_s3_body_to_file(resp, resolved, chunk_size)
            return resolved

        return await asyncio.to_thread(_download)

    async def exists(self, key: str) -> bool:
        return (await self.head_object(key)) is not None

    async def head_object(self, key: str) -> StoredObjectInfo | None:
        norm, obj_key = self._object_key(key)

        def _head() -> StoredObjectInfo | None:
            try:
                head = self._client.head_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    return None
                raise
            return _to_stored_info_from_head(norm, head)

        return await asyncio.to_thread(_head)

    async def list_objects(self, prefix: str = "") -> list[StoredObjectInfo]:
        clean = normalize_object_key(prefix.rstrip("/")) if prefix.strip("/") else ""
        if clean:
            base = f"{self._prefix}/{clean}" if self._prefix else clean
            full_prefix = f"{base}/" if prefix.endswith("/") else base
        else:
            full_prefix = f"{self._prefix}/" if self._prefix else ""

        def _list() -> list[StoredObjectInfo]:
            items: list[StoredObjectInfo] = []
            token: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": full_prefix}
                if token is not None:
                    kwargs["ContinuationToken"] = token
                resp = self._client.list_objects_v2(**kwargs)
                contents = resp.get("Contents") or []
                for entry in contents:
                    raw_key = str(entry.get("Key", ""))
                    rel = self._strip_prefix(raw_key)
                    if rel is None or not rel:
                        continue
                    etag = entry.get("ETag")
                    items.append(
                        StoredObjectInfo(
                            key=rel,
                            size_bytes=int(entry.get("Size", 0)),
                            last_modified=_parse_datetime(entry.get("LastModified")),
                            etag=str(etag).strip('"') if isinstance(etag, str) else None,
                        )
                    )
                if not resp.get("IsTruncated"):
                    break
                token = str(resp.get("NextContinuationToken") or "")
                if not token:
                    break
            return sorted(items, key=lambda item: item.key)

        return await asyncio.to_thread(_list)

    async def delete_object(self, key: str) -> bool:
        norm, obj_key = self._object_key(key)
        if await self.head_object(norm) is None:
            return False
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=obj_key)
        return True

    async def abort_incomplete_multipart_uploads(self, *, older_than_seconds: int = 3600) -> int:
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds must be >= 0")
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)

        def _abort() -> int:
            aborted = 0
            key_marker: str | None = None
            upload_marker: str | None = None
            while True:
                kwargs: dict[str, Any] = {"Bucket": self._bucket}
                if self._prefix:
                    kwargs["Prefix"] = f"{self._prefix}/"
                if key_marker is not None and upload_marker is not None:
                    kwargs["KeyMarker"] = key_marker
                    kwargs["UploadIdMarker"] = upload_marker
                resp = self._client.list_multipart_uploads(**kwargs)
                uploads = resp.get("Uploads") or []
                for upload in uploads:
                    initiated = _parse_datetime(upload.get("Initiated"))
                    if initiated is not None and initiated > cutoff:
                        continue
                    self._client.abort_multipart_upload(
                        Bucket=self._bucket,
                        Key=str(upload["Key"]),
                        UploadId=str(upload["UploadId"]),
                    )
                    aborted += 1
                if not resp.get("IsTruncated"):
                    break
                key_marker = str(resp.get("NextKeyMarker") or "")
                upload_marker = str(resp.get("NextUploadIdMarker") or "")
                if not key_marker or not upload_marker:
                    break
            return aborted

        return await asyncio.to_thread(_abort)

    async def cleanup_abandoned_temp_files(self, *, older_than_seconds: int = 1800) -> int:
        if not self._temp_dirs:
            return 0
        return await asyncio.to_thread(
            _cleanup_abandoned_in_dirs, self._temp_dirs, older_than_seconds=older_than_seconds
        )

    async def check_health(self) -> bool:
        """Probe S3/R2 bucket accessibility via HeadBucket without mutating objects."""
        head_bucket = getattr(self._client, "head_bucket", None)
        if not callable(head_bucket):
            return True

        def _probe() -> bool:
            try:
                head_bucket(Bucket=self._bucket)
                return True
            except Exception as exc:
                logger.warning("S3/R2 bucket health check failed for '%s': %s", self._bucket, exc)
                return False

        return await asyncio.to_thread(_probe)

    async def generate_presigned_download_url(
        self,
        key: str,
        *,
        expires_in: int = 300,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> str | None:
        """Generate a short-lived SigV4 presigned GET URL for private S3/R2 objects."""
        presign = getattr(self._client, "generate_presigned_url", None)
        if not callable(presign):
            return None
        norm, obj_key = self._object_key(key)
        safe_name = PurePosixPath(filename or norm).name or "download.bin"
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": obj_key,
            "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
        }
        if media_type:
            params["ResponseContentType"] = media_type

        def _sign() -> str:
            return str(
                presign(
                    "get_object",
                    Params=params,
                    ExpiresIn=max(30, min(int(expires_in), 86_400)),
                )
            )

        return await asyncio.to_thread(_sign)


def build_storage_port(settings: Settings) -> StoragePort:
    """Instantiate configured StoragePort adapter from service Settings."""
    temp_dirs = (
        (settings.ghs_storage_temp_dir,) if settings.ghs_storage_temp_dir is not None else ()
    )
    if settings.storage_backend == "local":
        return LocalObjectStore(settings.local_storage_dir, temp_dirs=temp_dirs)
    if not settings.s3_bucket:
        raise ValueError("s3_bucket must be configured when storage_backend='s3'")
    return S3ObjectStore(
        settings.s3_bucket,
        prefix=settings.s3_prefix,
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.effective_s3_access_key_id(),
        aws_secret_access_key=settings.effective_s3_secret_access_key(),
        temp_dirs=temp_dirs,
        connect_timeout_seconds=settings.s3_connect_timeout_seconds,
        read_timeout_seconds=settings.s3_read_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
    )
