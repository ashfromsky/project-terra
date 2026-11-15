"""Object storage port and concrete local/S3(Cloudflare R2) adapters for Core."""

import asyncio
import contextlib
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

import boto3
from botocore.config import Config as BotoConfig

from terra.config import Settings, normalize_s3_endpoint_url

logger = logging.getLogger("terra.object_storage")


def normalize_core_object_key(key: str) -> str:
    """Validate and normalize a relative POSIX object key against path traversal."""
    if not key or "\x00" in key or "\\" in key or key.startswith("/"):
        raise ValueError(f"Invalid object storage key: {key!r}")
    parts = key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe path segment in object storage key: {key!r}")
    return str(PurePosixPath(*parts))


def _is_not_found_error(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        err = resp.get("Error")
        if isinstance(err, dict):
            code = str(err.get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return True
        meta = resp.get("ResponseMetadata")
        if isinstance(meta, dict) and meta.get("HTTPStatusCode") == 404:
            return True
    return False


@dataclass(frozen=True, slots=True)
class StoredObjectDescriptor:
    """Metadata describing a stored object without exposing backend secrets."""

    key: str
    size_bytes: int
    content_type: str
    checksum_sha256: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None


class ObjectStoragePort(Protocol):
    """Unified async object storage port implemented for local disk and S3/R2."""

    @property
    def backend_name(self) -> Literal["local", "s3"]: ...

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> StoredObjectDescriptor: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def head_object(self, key: str) -> StoredObjectDescriptor | None: ...

    async def delete_object(self, key: str) -> bool: ...

    async def generate_presigned_download_url(
        self,
        key: str,
        *,
        expires_in: int = 300,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None: ...

    async def check_health(self) -> bool: ...


class LocalCoreObjectStore:
    """Atomic filesystem-backed object store matching S3 key semantics."""

    def __init__(self, root_dir: str | Path) -> None:
        self._root = Path(root_dir).expanduser().resolve()

    @property
    def backend_name(self) -> Literal["local", "s3"]:
        return "local"

    def _resolve(self, key: str) -> tuple[str, Path]:
        norm = normalize_core_object_key(key)
        resolved = (self._root / norm).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"Key '{key}' escapes Core object storage root")
        return norm, resolved

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> StoredObjectDescriptor:
        _ = metadata
        norm, dest = self._resolve(key)
        digest = hashlib.sha256(data).hexdigest()

        def _write() -> datetime:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".core-tmp-", dir=dest.parent)
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, dest)
            finally:
                with contextlib.suppress(OSError):
                    if tmp_path.exists():
                        tmp_path.unlink()
            return datetime.fromtimestamp(dest.stat().st_mtime, tz=UTC)

        mtime = await asyncio.to_thread(_write)
        return StoredObjectDescriptor(
            key=norm,
            size_bytes=len(data),
            content_type=content_type,
            checksum_sha256=digest,
            last_modified=mtime,
        )

    async def get_bytes(self, key: str) -> bytes:
        _, target = self._resolve(key)

        def _read() -> bytes:
            if not target.is_file():
                raise FileNotFoundError(f"Object not found in Core local store: {key}")
            return target.read_bytes()

        return await asyncio.to_thread(_read)

    async def head_object(self, key: str) -> StoredObjectDescriptor | None:
        norm, target = self._resolve(key)

        def _head() -> StoredObjectDescriptor | None:
            if not target.is_file():
                return None
            stat = target.stat()
            return StoredObjectDescriptor(
                key=norm,
                size_bytes=stat.st_size,
                content_type="application/octet-stream",
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )

        return await asyncio.to_thread(_head)

    async def delete_object(self, key: str) -> bool:
        _, target = self._resolve(key)

        def _delete() -> bool:
            if not target.is_file():
                return False
            target.unlink()
            return True

        return await asyncio.to_thread(_delete)

    async def generate_presigned_download_url(
        self,
        key: str,
        *,
        expires_in: int = 300,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        _ = (key, expires_in, filename, content_type)
        return None

    async def check_health(self) -> bool:
        def _probe() -> bool:
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self._root, prefix=".health-", delete=True):
                    return True
            except OSError:
                return False

        return await asyncio.to_thread(_probe)


class S3CoreObjectStore:
    """S3-compatible (Cloudflare R2) object store with SigV4 signing, retries, and presigning."""

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "core",
        endpoint_url: str | None = None,
        region_name: str = "auto",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        client: Any | None = None,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 60.0,
        max_attempts: int = 4,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket name must be non-empty")
        self._bucket = bucket.strip()
        clean_prefix = prefix.strip("/")
        self._prefix = normalize_core_object_key(clean_prefix) if clean_prefix else ""
        normalized_endpoint = normalize_s3_endpoint_url(endpoint_url, self._bucket)
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
            kwargs: dict[str, Any] = {
                "endpoint_url": normalized_endpoint,
                "region_name": self._region_name,
                "config": boto_cfg,
            }
            if aws_access_key_id:
                kwargs["aws_access_key_id"] = aws_access_key_id
            if aws_secret_access_key:
                kwargs["aws_secret_access_key"] = aws_secret_access_key
            self._client = boto3.client("s3", **kwargs)

    @property
    def backend_name(self) -> Literal["local", "s3"]:
        return "s3"

    def _object_key(self, key: str) -> tuple[str, str]:
        norm = normalize_core_object_key(key)
        full = f"{self._prefix}/{norm}" if self._prefix else norm
        return norm, full

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> StoredObjectDescriptor:
        norm, obj_key = self._object_key(key)
        digest = hashlib.sha256(data).hexdigest()
        s3_meta = {"sha256": digest}
        if metadata:
            for mk, mv in metadata.items():
                if mk and mv:
                    s3_meta[mk.lower()] = str(mv)[:256]

        def _put() -> tuple[str | None, datetime | None]:
            resp = self._client.put_object(
                Bucket=self._bucket,
                Key=obj_key,
                Body=data,
                ContentType=content_type,
                Metadata=s3_meta,
            )
            head = self._client.head_object(Bucket=self._bucket, Key=obj_key)
            content_len = int(head.get("ContentLength", -1))
            if content_len != len(data):
                raise OSError(
                    f"S3 post-upload size mismatch for '{obj_key}': "
                    f"expected {len(data)}, got {content_len}"
                )
            etag = resp.get("ETag") or head.get("ETag")
            modified = head.get("LastModified")
            return (
                str(etag).strip('"') if isinstance(etag, str) else None,
                modified if isinstance(modified, datetime) else None,
            )

        etag, modified = await asyncio.to_thread(_put)
        return StoredObjectDescriptor(
            key=norm,
            size_bytes=len(data),
            content_type=content_type,
            checksum_sha256=digest,
            etag=etag,
            last_modified=modified,
        )

    async def get_bytes(self, key: str) -> bytes:
        _, obj_key = self._object_key(key)

        def _get() -> bytes:
            try:
                resp = self._client.get_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    raise FileNotFoundError(f"Object not found in S3: {obj_key}") from exc
                raise
            body = resp.get("Body")
            if isinstance(body, (bytes, bytearray)):
                return bytes(body)
            read_fn = getattr(body, "read", None)
            close_fn = getattr(body, "close", None)
            if not callable(read_fn):
                raise OSError("S3 response missing readable Body")
            try:
                raw = read_fn()
                return bytes(raw)
            finally:
                if callable(close_fn):
                    close_fn()

        return await asyncio.to_thread(_get)

    async def head_object(self, key: str) -> StoredObjectDescriptor | None:
        norm, obj_key = self._object_key(key)

        def _head() -> StoredObjectDescriptor | None:
            try:
                head = self._client.head_object(Bucket=self._bucket, Key=obj_key)
            except Exception as exc:
                if _is_not_found_error(exc):
                    return None
                raise
            meta = head.get("Metadata")
            sha = meta.get("sha256") if isinstance(meta, dict) else None
            etag = head.get("ETag")
            modified = head.get("LastModified")
            return StoredObjectDescriptor(
                key=norm,
                size_bytes=int(head.get("ContentLength", 0)),
                content_type=str(head.get("ContentType", "application/octet-stream")),
                checksum_sha256=str(sha) if isinstance(sha, str) else None,
                etag=str(etag).strip('"') if isinstance(etag, str) else None,
                last_modified=modified if isinstance(modified, datetime) else None,
            )

        return await asyncio.to_thread(_head)

    async def delete_object(self, key: str) -> bool:
        norm, obj_key = self._object_key(key)
        if await self.head_object(norm) is None:
            return False
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=obj_key)
        return True

    async def generate_presigned_download_url(
        self,
        key: str,
        *,
        expires_in: int = 300,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str | None:
        presign = getattr(self._client, "generate_presigned_url", None)
        if not callable(presign):
            return None
        norm, obj_key = self._object_key(key)
        safe_name = PurePosixPath(filename or norm).name or "artifact.bin"
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": obj_key,
            "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
        }
        if content_type:
            params["ResponseContentType"] = content_type

        def _sign() -> str:
            return str(
                presign(
                    "get_object",
                    Params=params,
                    ExpiresIn=max(30, min(int(expires_in), 86_400)),
                )
            )

        return await asyncio.to_thread(_sign)

    async def check_health(self) -> bool:
        def _probe() -> bool:
            try:
                self._client.head_bucket(Bucket=self._bucket)
                return True
            except Exception as exc:
                logger.warning("Core S3/R2 health check failed for '%s': %s", self._bucket, exc)
                return False

        return await asyncio.to_thread(_probe)


def build_core_object_storage(settings: Settings) -> ObjectStoragePort:
    """Instantiate configured Core object storage adapter from Settings."""
    if settings.storage_backend == "local":
        base = settings.scientific_artifact_dir or ".data/artifacts"
        return LocalCoreObjectStore(base)
    if not settings.s3_bucket:
        raise ValueError("S3_BUCKET must be configured when STORAGE_BACKEND=s3")
    return S3CoreObjectStore(
        settings.s3_bucket,
        prefix=settings.core_s3_prefix,
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.effective_s3_access_key_id(),
        aws_secret_access_key=settings.effective_s3_secret_access_key(),
        connect_timeout_seconds=settings.s3_connect_timeout_seconds,
        read_timeout_seconds=settings.s3_read_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
    )
