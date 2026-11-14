"""StoragePort implementations for local filesystem and S3-compatible object stores."""

import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from geospatial_harmonization.domain.models.dataset import AssetReference, DataFormat

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
