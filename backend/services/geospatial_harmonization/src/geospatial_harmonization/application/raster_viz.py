"""Raster tile rendering, bounding-box PNG export, and point pixel inspection for GHS."""

import asyncio
import contextlib
import hashlib
import logging
import math
import os
import re
import struct
import tempfile
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer
from rasterio.errors import WindowError
from rasterio.warp import transform_bounds

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    ScratchCapacityError,
    scratch_capacity_error_from_oserror,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    SpatialDataset,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.ports import StoragePort
from geospatial_harmonization.readers import ReaderRegistry
from geospatial_harmonization.transformations._warp import (
    orient_to_north_up,
    to_rasterio_affine,
    warp_variable,
)

_ORIGIN_SHIFT = 20037508.342789244
_SUPPORTED_RASTER_FORMATS: frozenset[DataFormat] = frozenset(
    {"geotiff", "hdf4", "hdf5", "netcdf", "zarr"}
)
_QA_TOKENS = ("qa", "qc", "qual", "flag", "reliability", "bitmask", "lat", "lon")

logger = logging.getLogger(__name__)

_CACHE_SWEEP_LOCK = threading.Lock()


def _pid_alive(pid: int) -> bool:
    """POSIX liveness probe for a cache-entry owner pid."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, OSError):
        return False
    return True


# ---------------------------------------------------------------------------
# Bounded materialized-asset cache
#
# Materialized raster assets are cached on disk under
# ``<GHS_STORAGE_TEMP_DIR | system tmp>/ghs_raster_cache``. Files are named
# ``{key}.{pid}.{hint}`` so a process restart can identify and drop entries
# created by dead processes. In-memory accounting is deliberately per-process:
# the ownership marker in each filename lets a fresh process reclaim the
# on-disk leftovers of its predecessors without removing files actively used
# by other live workers.
#
# Concurrency model:
# - Per-key asyncio locks prevent duplicate concurrent materialization.
# - Check-out/check-in reference counts protect files rendered by in-flight
#   requests; eviction skips entries currently in use and deletes deferred
#   evictions once the last user checks in.
# ---------------------------------------------------------------------------

_ASSET_CACHE_DIRNAME = "ghs_raster_cache"
_ASSET_CACHE_MAX_BYTES = 256 * 1024 * 1024
_ASSET_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_ASSET_CACHE_ENTRIES: OrderedDict[str, tuple[Path, int]] = OrderedDict()
_ASSET_CACHE_TOTAL_BYTES = 0
_ASSET_CACHE_IN_USE: dict[str, int] = {}
_ASSET_CACHE_EVICTION_PENDING: dict[str, Path] = {}
_CACHE_SWEEP_DONE = False

# Assets whose known size exceeds half the cache budget are never persisted
# into the cache directory; they are materialized once, per request, into the
# request-owned scratch directory instead.
_MAX_CACHEABLE_ASSET_BYTES = _ASSET_CACHE_MAX_BYTES // 2


def _resolve_cache_dir() -> Path:
    from geospatial_harmonization.storage.scratch import scratch_base_dir

    return scratch_base_dir() / _ASSET_CACHE_DIRNAME


def _scratch_base() -> Path:
    """Scratch base directory for render/point-query TemporaryDirectory targets."""
    from geospatial_harmonization.storage.scratch import scratch_base_dir

    return scratch_base_dir()


_CACHE_NAME_PATTERN = re.compile(r"^(?P<key>[0-9a-f]{24})\.(?P<pid>\d+)\.")


def _cache_pid_alive(name: str) -> bool | None:
    """Return entry-pid liveness parsed from a cache filename, None if unnamed."""
    match = _CACHE_NAME_PATTERN.match(name)
    if match is None:
        return None
    return _pid_alive(int(match.group("pid")))


def _sweep_stale_cache_entries() -> None:
    """One-time per-process scan removing cache files owned by dead processes.

    Unparseable files (e.g. leftovers from a previous format or interrupted
    moves) are removed once their age exceeds the abandoned-temp grace period.
    """
    global _CACHE_SWEEP_DONE
    cache_dir = _resolve_cache_dir()
    if not cache_dir.is_dir():
        return
    from geospatial_harmonization.storage.scratch import (
        get_settings as scratch_get_settings,
    )

    max_age = scratch_get_settings().ghs_storage_abandoned_temp_max_age_seconds
    now = time.time()
    removed = 0
    try:
        with os.scandir(cache_dir) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                alive = _cache_pid_alive(entry.name)
                if alive is False or (alive is None and now - entry.stat().st_mtime > max_age):
                    with contextlib.suppress(OSError):
                        Path(entry.path).unlink(missing_ok=True)
                        removed += 1
    except OSError:
        logger.debug("Raster cache sweep scan failed for %s", cache_dir, exc_info=True)
    if removed:
        logger.info("Removed %d raster cache entries from dead processes", removed)


def _ensure_cache_swept() -> None:
    global _CACHE_SWEEP_DONE
    if _CACHE_SWEEP_DONE:
        return
    with contextlib.suppress(Exception):
        _sweep_stale_cache_entries()
    _CACHE_SWEEP_DONE = True


def _cache_entry_key(asset: AssetReference, storage: StoragePort) -> str:
    raw = (
        f"{id(storage)}|{asset.storage_key or ''}|"
        f"{asset.checksum_sha256 or ''}|{asset.size_bytes or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _evict_asset_cache_if_needed() -> None:
    global _ASSET_CACHE_TOTAL_BYTES
    while _ASSET_CACHE_TOTAL_BYTES > _ASSET_CACHE_MAX_BYTES:
        victim: str | None = None
        for key in _ASSET_CACHE_ENTRIES:  # oldest (LRU) first
            if _ASSET_CACHE_IN_USE.get(key, 0) == 0:
                victim = key
                break
        if victim is None:
            # Every entry is in active use by a concurrent render; allow the
            # bounded overshoot and retry eviction on the next check-in.
            return
        entry: tuple[Path, int] = _ASSET_CACHE_ENTRIES.pop(victim)
        old_path, old_size = entry
        _ASSET_CACHE_TOTAL_BYTES = max(0, _ASSET_CACHE_TOTAL_BYTES - old_size)
        with contextlib.suppress(OSError):
            old_path.unlink(missing_ok=True)


def _checkout_cached(cache_key: str) -> Path | None:
    """Return a checked-out (ref-counted) cache path, or None when absent."""
    with _CACHE_SWEEP_LOCK:
        cached = _ASSET_CACHE_ENTRIES.get(cache_key)
        if cached is None:
            return None
        cached_path, _ = cached
        if not cached_path.is_file():
            _ASSET_CACHE_ENTRIES.pop(cache_key, None)
            return None
        _ASSET_CACHE_IN_USE[cache_key] = _ASSET_CACHE_IN_USE.get(cache_key, 0) + 1
        _ASSET_CACHE_ENTRIES.move_to_end(cache_key)
        return cached_path


def _checkin_cached(cache_key: str) -> None:
    with _CACHE_SWEEP_LOCK:
        remaining = _ASSET_CACHE_IN_USE.get(cache_key, 1) - 1
        if remaining > 0:
            _ASSET_CACHE_IN_USE[cache_key] = remaining
            return
        _ASSET_CACHE_IN_USE.pop(cache_key, None)
        pending = _ASSET_CACHE_EVICTION_PENDING.pop(cache_key, None)
        entry = _ASSET_CACHE_ENTRIES.get(cache_key)
        if entry is None and pending is not None:
            with contextlib.suppress(OSError):
                pending.unlink(missing_ok=True)


class _CheckedOutCacheAsset:
    """Owns a checked-out or request-owned materialized path until check-in."""

    def __init__(self, path: Path, cache_key: str | None) -> None:
        self.path = path
        self.cache_key = cache_key

    def release(self) -> None:
        if self.cache_key is not None:
            _checkin_cached(self.cache_key)


def _known_asset_bytes(asset: AssetReference, head_size: int | None) -> int | None:
    """Best-effort metadata size for the asset, preferring explicit bytes."""
    if asset.size_bytes and asset.size_bytes > 0:
        return int(asset.size_bytes)
    return head_size


async def _materialize_asset(
    asset: AssetReference,
    storage: StoragePort | None,
    tmp_dir: Path,
) -> _CheckedOutCacheAsset:
    """Materialize a renderable asset, caching small assets under the cache dir.

    Returns a checked-out handle: callers must invoke ``release()`` when the
    path is no longer being read so eviction can reclaim it safely.
    """
    global _ASSET_CACHE_TOTAL_BYTES
    _ensure_cache_swept()
    from geospatial_harmonization.storage.scratch import check_scratch_capacity

    source_name = asset.storage_key or urlparse(asset.uri).path or "asset.bin"
    name_hint = Path(source_name).name or "asset.bin"
    dest = tmp_dir / name_hint
    if asset.storage_key and storage is not None:
        cache_key = _cache_entry_key(asset, storage)
        checked_out = _checkout_cached(cache_key)
        if checked_out is not None:
            return _CheckedOutCacheAsset(checked_out, cache_key)

        lock = _ASSET_CACHE_LOCKS.setdefault(cache_key, asyncio.Lock())
        async with lock:
            checked_out = _checkout_cached(cache_key)
            if checked_out is not None:
                return _CheckedOutCacheAsset(checked_out, cache_key)

            head_size: int | None = None
            if asset.size_bytes is None or asset.size_bytes <= 0:
                with contextlib.suppress(Exception):
                    info = await storage.head_object(asset.storage_key)
                    if info is not None:
                        head_size = info.size_bytes
            known_size = _known_asset_bytes(asset, head_size)

            # Metadata-based sizing prevents streaming oversized assets into the
            # persistent cache at all; they go straight to the request scratch dir.
            cacheable = known_size is not None and known_size <= _MAX_CACHEABLE_ASSET_BYTES
            if known_size is not None and cacheable:
                try:
                    check_scratch_capacity(None, known_size)
                except ScratchCapacityError:
                    cacheable = False

            cache_file = _resolve_cache_dir() / f"{cache_key}.{os.getpid()}.{name_hint}"
            try:
                if cacheable:
                    _resolve_cache_dir().mkdir(parents=True, exist_ok=True)
                    materialized = await storage.materialize_to_path(asset.storage_key, cache_file)
                    size = materialized.stat().st_size if materialized.is_file() else 0
                    if size <= 0 or size > _MAX_CACHEABLE_ASSET_BYTES:
                        # Single-download oversized asset: hand it to this
                        # request directly without registering it in the cache.
                        return _CheckedOutCacheAsset(materialized, None)
                    _ASSET_CACHE_ENTRIES[cache_key] = (materialized, size)
                    _ASSET_CACHE_TOTAL_BYTES += size
                    _evict_asset_cache_if_needed()
                    checked_out = _checkout_cached(cache_key)
                    if checked_out is not None:
                        return _CheckedOutCacheAsset(checked_out, cache_key)
                    return _CheckedOutCacheAsset(materialized, None)
                # Unknown or oversized assets stream into the request scratch
                # dir; unknown-size downloads that turn out small are then
                # moved into the cache, never re-downloaded.
                storage_path = await storage.materialize_to_path(asset.storage_key, dest)
                size = storage_path.stat().st_size if storage_path.is_file() else 0
                if known_size is None and 0 < size <= _MAX_CACHEABLE_ASSET_BYTES:
                    try:
                        _resolve_cache_dir().mkdir(parents=True, exist_ok=True)
                        os.replace(storage_path, cache_file)
                    except OSError:
                        logger.debug(
                            "Could not move asset %s into cache; using request dir",
                            asset.storage_key,
                            exc_info=True,
                        )
                    else:
                        _ASSET_CACHE_ENTRIES[cache_key] = (cache_file, size)
                        _ASSET_CACHE_TOTAL_BYTES += size
                        _evict_asset_cache_if_needed()
                        checked_out = _checkout_cached(cache_key)
                        if checked_out is not None:
                            return _CheckedOutCacheAsset(checked_out, cache_key)
                        return _CheckedOutCacheAsset(cache_file, None)
                return _CheckedOutCacheAsset(storage_path, None)
            except FileNotFoundError:
                pass
            except OSError as exc:
                capacity = scratch_capacity_error_from_oserror(exc)
                if capacity is not None:
                    raise capacity from exc
                logger.warning(
                    "Materialization from storage failed for key '%s': %s",
                    asset.storage_key,
                    exc,
                )
            except ScratchCapacityError:
                raise
            except Exception as exc:
                logger.warning(
                    "Materialization from storage failed for key '%s': %s",
                    asset.storage_key,
                    exc,
                )
    local_candidate = _local_path_from_uri(asset.uri)
    if local_candidate is not None:
        return _CheckedOutCacheAsset(local_candidate, None)
    if storage is not None and asset.storage_key:
        try:
            data = await storage.get_bytes(asset.storage_key)
        except FileNotFoundError as exc:
            raise RasterAssetUnavailableError(
                f"Raster asset '{asset.asset_id}' was not found in storage."
            ) from exc
        except Exception as exc:
            raise RasterAssetUnavailableError(
                f"Failed to read raster asset '{asset.asset_id}' from storage: {exc}"
            ) from exc
        try:
            dest.write_bytes(data)
        except OSError as exc:
            capacity = scratch_capacity_error_from_oserror(exc)
            if capacity is not None:
                raise capacity from exc
            raise
        return _CheckedOutCacheAsset(dest, None)
    raise RasterAssetUnavailableError(
        f"Raster asset '{asset.asset_id}' could not be materialized from storage."
    )


class UnsupportedRasterFormatError(IncompatibleDatasetError):
    """Raised when a dataset lacks a renderable raster asset (e.g. Zarr or tabular JSON/CSV)."""


class RasterAssetUnavailableError(IncompatibleDatasetError):
    """Raised when no materialized asset file can be opened from storage."""


class RasterVariableNotFoundError(IncompatibleDatasetError):
    """Raised when a requested raster variable is absent from the decoded asset."""


_ColorStop = tuple[float, tuple[int, int, int]]

_COLOR_RAMPS: dict[str, tuple[float, float, tuple[_ColorStop, ...]]] = {
    "ndvi": (
        0.0,
        1.0,
        (
            (0.0, (223, 184, 146)),
            (0.25, (217, 227, 163)),
            (0.55, (116, 196, 118)),
            (0.85, (35, 132, 67)),
            (1.0, (15, 92, 58)),
        ),
    ),
    "evi": (
        0.0,
        0.8,
        (
            (0.0, (229, 203, 176)),
            (0.28, (220, 228, 194)),
            (0.56, (142, 199, 190)),
            (0.88, (14, 124, 116)),
            (1.0, (13, 79, 54)),
        ),
    ),
    "lst_celsius": (
        -10.0,
        45.0,
        (
            (0.0, (49, 147, 206)),
            (0.40, (164, 207, 202)),
            (0.65, (234, 214, 188)),
            (1.0, (199, 127, 109)),
        ),
    ),
    "precip": (
        0.0,
        25.0,
        (
            (0.0, (247, 251, 255)),
            (0.15, (198, 219, 239)),
            (0.40, (107, 174, 214)),
            (0.70, (33, 113, 181)),
            (1.0, (8, 48, 107)),
        ),
    ),
    "soil_moisture": (
        0.02,
        0.55,
        (
            (0.0, (222, 180, 159)),
            (0.30, (232, 233, 219)),
            (0.60, (145, 198, 188)),
            (1.0, (49, 147, 206)),
        ),
    ),
    "viridis": (
        0.0,
        1.0,
        (
            (0.0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.50, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1.0, (253, 231, 37)),
        ),
    ),
}


def encode_rgba_png(rgba: NDArray[np.uint8]) -> bytes:
    """Encode an (H, W, 4) uint8 RGBA array cleanly as a PNG binary payload."""
    arr = np.ascontiguousarray(rgba, dtype=np.uint8)
    height, width, channels = arr.shape
    if channels != 4:
        raise ValueError(f"Expected 4-channel RGBA array, got shape {arr.shape}")

    raw_rows = b"".join(b"\x00" + arr[row].tobytes() for row in range(height))
    compressed = zlib.compress(raw_rows, level=6)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", compressed),
            _chunk(b"IEND", b""),
        )
    )


def _transparent_png(width: int, height: int) -> bytes:
    return encode_rgba_png(np.zeros((height, width, 4), dtype=np.uint8))


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Compute Web Mercator (EPSG:3857) bounds for an XYZ tile."""
    n = float(2**z)
    tile_span = (2.0 * _ORIGIN_SHIFT) / n
    min_x = -_ORIGIN_SHIFT + x * tile_span
    max_x = min_x + tile_span
    max_y = _ORIGIN_SHIFT - y * tile_span
    min_y = max_y - tile_span
    return (min_x, min_y, max_x, max_y)


def _dataset_wgs84_bounds(dataset: SpatialDataset) -> tuple[float, float, float, float] | None:
    bounds = dataset.spatial_metadata.bounds
    crs = dataset.spatial_metadata.crs
    if bounds is not None:
        if crs is None or "4326" in crs:
            return bounds.as_tuple()
        w, s, e, n = transform_bounds(crs, "EPSG:4326", *bounds.as_tuple(), densify_pts=21)
        return (float(w), float(s), float(e), float(n))
    grid = dataset.spatial_metadata.grid
    if grid is not None:
        gb = grid.bounds.as_tuple()
        if "4326" in grid.crs:
            return gb
        w, s, e, n = transform_bounds(grid.crs, "EPSG:4326", *gb, densify_pts=21)
        return (float(w), float(s), float(e), float(n))
    return None


def _bounds_intersect(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _extract_timestamps_list(dataset: SpatialDataset, variable: str | None) -> list[str]:
    ts_ext = dataset.extensions.get("time_series")
    if not isinstance(ts_ext, Mapping):
        return []
    if variable and isinstance(ts_ext.get(variable), Mapping):
        raw_ts = ts_ext[variable].get("timestamps")
        if isinstance(raw_ts, list):
            return [str(t) for t in raw_ts]
    for entry in ts_ext.values():
        if isinstance(entry, Mapping):
            raw_ts = entry.get("timestamps")
            if isinstance(raw_ts, list) and raw_ts:
                return [str(t) for t in raw_ts]
    return []


def _parse_utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _select_step_index(timestamps: list[str], timestamp: str | None) -> int:
    if not timestamps or not timestamp:
        return 0
    target = timestamp.strip()
    target_date = target[:10]
    for idx, ts in enumerate(timestamps):
        if ts == target or ts[:10] == target_date:
            return idx
    target_dt = _parse_utc_datetime(target)
    if target_dt is None:
        return 0
    best_idx = 0
    best_diff: float | None = None
    for idx, ts in enumerate(timestamps):
        dt = _parse_utc_datetime(ts)
        if dt is None:
            continue
        diff = abs((dt - target_dt).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = idx
    return best_idx


def _select_candidate_raster_assets(
    dataset: SpatialDataset,
    *,
    timestamp: str | None = None,
    variable: str | None = None,
    prefer_raw: bool = False,
) -> list[tuple[AssetReference, int]]:
    if not dataset.assets:
        raise RasterAssetUnavailableError(f"Dataset '{dataset.dataset_id}' has no stored assets.")
    raster_assets = [a for a in dataset.assets if a.data_format in _SUPPORTED_RASTER_FORMATS]
    if not raster_assets:
        formats = ", ".join(sorted({a.data_format for a in dataset.assets}))
        raise UnsupportedRasterFormatError(
            f"Dataset '{dataset.dataset_id}' assets ({formats}) "
            "are not directly renderable raster formats."
        )

    timestamps = _extract_timestamps_list(dataset, variable)
    step_idx = _select_step_index(timestamps, timestamp)

    def _is_asset_file_on_disk(a: AssetReference) -> bool:
        if a.uri.startswith("file://"):
            try:
                p = Path(unquote(urlparse(a.uri).path))
                return p.is_file()
            except Exception:
                return False
        return True

    def _var_match_score(a: AssetReference) -> int:
        if not variable:
            return 1
        var_tokens = [
            variable.lower(),
            variable.lower().replace(" ", "_"),
            variable.lower().replace(" ", "-"),
        ]
        haystack = f"{a.asset_id} {a.storage_key or ''} {a.uri}".lower()
        if any(tok in haystack for tok in var_tokens):
            return 2
        if a.zone == "raw" or a.data_format in {"hdf4", "hdf5", "netcdf", "zarr"}:
            return 1
        return 0

    def _time_match_score(a: AssetReference) -> int:
        if not timestamp:
            return 1
        date_str = timestamp[:10]
        compact_date = date_str.replace("-", "")
        julian_tokens: tuple[str, ...] = ()
        try:
            dt_day = datetime.fromisoformat(date_str)
            yyyyddd = dt_day.strftime("%Y%j")
            julian_tokens = (f"A{yyyyddd}", yyyyddd)
        except ValueError:
            pass
        haystack = f"{a.asset_id} {a.storage_key or ''} {a.uri}"
        if (
            compact_date in haystack
            or date_str in haystack
            or any(tok in haystack for tok in julian_tokens)
        ):
            return 2
        return 1

    geotiff_assets = [a for a in raster_assets if a.data_format in {"geotiff", "cog"}]
    raw_assets = [
        a
        for a in raster_assets
        if a.zone == "raw" or a.data_format in {"hdf4", "hdf5", "netcdf", "zarr"}
    ]
    other_assets = [a for a in raster_assets if a not in geotiff_assets and a not in raw_assets]

    def _sort_key(a: AssetReference) -> tuple[int, int]:
        return (
            _var_match_score(a),
            _time_match_score(a),
        )

    geotiff_assets.sort(key=_sort_key, reverse=True)
    raw_assets.sort(key=_sort_key, reverse=True)
    other_assets.sort(key=_sort_key, reverse=True)

    available_geotiff = [a for a in geotiff_assets if _is_asset_file_on_disk(a)]
    missing_geotiff = [a for a in geotiff_assets if not _is_asset_file_on_disk(a)]

    available_raw = [a for a in raw_assets if _is_asset_file_on_disk(a)]
    missing_raw = [a for a in raw_assets if not _is_asset_file_on_disk(a)]

    available_other = [a for a in other_assets if _is_asset_file_on_disk(a)]
    missing_other = [a for a in other_assets if not _is_asset_file_on_disk(a)]

    if prefer_raw:
        available = available_raw + available_geotiff + available_other
        missing = missing_raw + missing_geotiff + missing_other
    else:
        available = available_geotiff + available_raw + available_other
        missing = missing_geotiff + missing_raw + missing_other

    ordered = available + missing

    seen: set[str] = set()
    unique_candidates: list[tuple[AssetReference, int]] = []
    for a in ordered:
        if a.asset_id not in seen:
            seen.add(a.asset_id)
            s_idx = 0 if timestamp and _time_match_score(a) == 2 else step_idx
            unique_candidates.append((a, s_idx))

    if not unique_candidates:
        raise RasterAssetUnavailableError(
            f"Dataset '{dataset.dataset_id}' has no matching raster assets."
        )
    return unique_candidates


def _select_raster_asset(
    dataset: SpatialDataset,
    *,
    timestamp: str | None = None,
    variable: str | None = None,
    prefer_raw: bool = False,
) -> tuple[AssetReference, int]:
    candidates = _select_candidate_raster_assets(
        dataset, timestamp=timestamp, variable=variable, prefer_raw=prefer_raw
    )
    return candidates[0]


def _local_path_from_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        candidate = Path(unquote(parsed.path))
        return candidate if (candidate.is_file() or candidate.is_dir()) else None
    if not parsed.scheme:
        candidate = Path(uri)
        return candidate if (candidate.is_file() or candidate.is_dir()) else None
    return None


def _match_variable_name(candidates: list[str], requested: str) -> str | None:
    req_low = requested.strip().lower()
    for name in candidates:
        if name.lower() == req_low:
            return name
    for name in candidates:
        leaf = name.rsplit("/", 1)[-1].lower()
        if leaf == req_low:
            return name
    for name in candidates:
        low = name.lower()
        if low.endswith(f" {req_low}") or low.endswith(f"/{req_low}"):
            return name
    return None


def _merge_dataset_variable_spec(
    matched: str,
    decoded_spec: VariableSpec,
    dataset: SpatialDataset,
    preferred_ds_var: str | None = None,
) -> VariableSpec:
    ds_spec = dataset.variables.get(preferred_ds_var) if preferred_ds_var else None
    if ds_spec is None:
        ds_match = _match_variable_name(list(dataset.variables.keys()), matched)
        if ds_match is not None:
            ds_spec = dataset.variables[ds_match]
    if ds_spec is None:
        quant_ds_vars = [
            spec
            for spec in dataset.variables.values()
            if spec.semantics not in ("qa_flag", "categorical", "coordinate")
        ]
        if len(quant_ds_vars) == 1:
            ds_spec = quant_ds_vars[0]
    if ds_spec is None:
        return decoded_spec
    resolved_units = (
        ds_spec.units
        if decoded_spec.units in ("1", "dimensionless", "unknown") and ds_spec.units
        else decoded_spec.units
    )
    decoded_is_float = np.dtype(decoded_spec.dtype).kind == "f"
    # Never apply integer packing scale/offset from dataset metadata onto an already-float raster.
    resolved_scale = (
        decoded_spec.scale_factor
        if decoded_is_float or ds_spec.scale_factor is None
        else ds_spec.scale_factor
    )
    resolved_offset = (
        decoded_spec.add_offset
        if decoded_is_float or ds_spec.add_offset is None
        else ds_spec.add_offset
    )
    return replace(
        decoded_spec,
        units=resolved_units,
        nodata=decoded_spec.nodata if decoded_spec.nodata is not None else ds_spec.nodata,
        scale_factor=resolved_scale,
        add_offset=resolved_offset,
        valid_range=(
            ds_spec.valid_range if ds_spec.valid_range is not None else decoded_spec.valid_range
        ),
    )


def _select_raster_variable(
    decoded: DecodedDataset,
    dataset: SpatialDataset,
    variable: str | None,
) -> tuple[str, VariableSpec]:
    quant_names = [
        name
        for name, spec in decoded.variables.items()
        if spec.semantics not in ("qa_flag", "categorical", "coordinate")
        and name in decoded.arrays
        and not any(tok in name.rsplit("/", 1)[-1].lower() for tok in _QA_TOKENS)
    ]
    all_names = [name for name in decoded.variables if name in decoded.arrays]
    if variable is not None:
        matched = _match_variable_name(quant_names, variable) or _match_variable_name(
            all_names, variable
        )
        if matched is None and len(quant_names) == 1 and variable in dataset.variables:
            matched = quant_names[0]
        elif matched is None:
            raise RasterVariableNotFoundError(
                f"Variable '{variable}' not found in raster asset (available: {all_names})."
            )
        return matched, _merge_dataset_variable_spec(
            matched, decoded.variables[matched], dataset, variable
        )

    for ds_var in dataset.variables:
        matched = _match_variable_name(quant_names, ds_var)
        if matched is not None:
            return matched, _merge_dataset_variable_spec(
                matched, decoded.variables[matched], dataset, ds_var
            )

    if quant_names:
        first = quant_names[0]
        return first, _merge_dataset_variable_spec(first, decoded.variables[first], dataset)
    raise RasterVariableNotFoundError("No continuous scientific raster variable found in asset.")


def _find_qa_variable(
    decoded: DecodedDataset,
    product: str,
    target_var: str,
    target_shape: tuple[int, int],
) -> str | None:
    preferred: tuple[str, ...]
    upper = product.upper()
    if "MOD13" in upper:
        preferred = (
            "250m 16 days pixel reliability",
            "pixel_reliability",
            "250m 16 days VI Quality",
        )
    elif "MOD11" in upper:
        preferred = (
            ("QC_Night", "QC_Day") if "night" in target_var.lower() else ("QC_Day", "QC_Night")
        )
    elif "IMERG" in upper:
        preferred = ("precipitationQualityIndex", "Grid/precipitationQualityIndex")
    elif "SPL3SMP" in upper:
        preferred = (
            "retrieval_qual_flag",
            "Soil_Moisture_Retrieval_Data_AM/retrieval_qual_flag",
            "surface_flag",
        )
    else:
        preferred = ()

    for key in preferred:
        if key in decoded.arrays:
            arr = np.asarray(decoded.arrays[key])
            if arr.shape[-2:] == target_shape:
                return key

    for name, spec in decoded.variables.items():
        if spec.semantics == "qa_flag" and name in decoded.arrays:
            arr = np.asarray(decoded.arrays[name])
            if arr.shape[-2:] == target_shape:
                return name
    return None


def _is_kelvin_unit(unit: str) -> bool:
    return unit.strip().lower() in {"k", "kelvin", "kelvins"}


def _is_celsius_unit(unit: str) -> bool:
    low = unit.strip().lower()
    return low in {"°c", "c", "celsius", "degc", "deg_c"}


def _should_convert_kelvin_to_celsius(
    spec: VariableSpec,
    dataset: SpatialDataset,
    colormap: str | None,
    unit_conversion: str | None,
    sample_values: NDArray[np.float64] | None = None,
) -> bool:
    wants_conversion = unit_conversion == "kelvin_to_celsius" or colormap == "lst_celsius"
    if not wants_conversion:
        return False
    spec_unit = spec.units.strip()
    ds_unit = dataset.units.get(spec.name, spec.units).strip()
    if _is_celsius_unit(spec_unit) or _is_celsius_unit(ds_unit):
        return False
    if _is_kelvin_unit(spec_unit) or _is_kelvin_unit(ds_unit):
        if sample_values is not None and sample_values.size > 0:
            finite = sample_values[np.isfinite(sample_values)]
            if finite.size > 0 and float(np.nanmean(finite)) < 120.0:
                return False
        return True
    if (
        unit_conversion == "kelvin_to_celsius"
        and sample_values is not None
        and sample_values.size > 0
    ):
        finite = sample_values[np.isfinite(sample_values)]
        return finite.size > 0 and float(np.nanmean(finite)) > 150.0
    return False


def _evaluate_qa_mask(
    product: str,
    qa_arr: NDArray[np.generic],
    qa_var_name: str,
) -> NDArray[np.bool_]:
    upper = product.upper()
    arr_f = np.asarray(qa_arr, dtype=np.float64)
    finite = np.isfinite(arr_f)
    if "MOD13" in upper:
        qa_int = np.where(finite, arr_f, -1).astype(np.int64)
        if "vi quality" in qa_var_name.lower():
            return np.asarray(finite & ((qa_int & 0b11) <= 1), dtype=np.bool_)
        return np.asarray(finite & ((qa_int == 0) | (qa_int == 1)), dtype=np.bool_)
    if "MOD11" in upper:
        qa_int = np.where(finite, arr_f, -1).astype(np.int64)
        mandatory = qa_int & 0b11
        err_bits = (qa_int >> 6) & 0b11
        return np.asarray(
            finite & (qa_int >= 0) & (mandatory <= 1) & (err_bits <= 1), dtype=np.bool_
        )
    if "IMERG" in upper:
        return np.asarray(finite & (arr_f >= 0.5), dtype=np.bool_)
    if "SPL3SMP" in upper:
        qa_int = np.where(finite, arr_f, -1).astype(np.int64)
        return np.asarray(finite & (qa_int >= 0) & ((qa_int & 0b1) == 0), dtype=np.bool_)
    return np.ones(qa_arr.shape, dtype=bool)


def _colorize_values(
    values: NDArray[np.float64],
    valid_mask: NDArray[np.bool_],
    *,
    colormap: str,
    vmin: float | None,
    vmax: float | None,
) -> NDArray[np.uint8]:
    default_min, default_max, stops = _COLOR_RAMPS.get(colormap, _COLOR_RAMPS["viridis"])
    lo = default_min if vmin is None else float(vmin)
    hi = default_max if vmax is None else float(vmax)
    if hi <= lo:
        hi = lo + 1e-6

    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if not np.any(valid_mask):
        return rgba

    stop_t = np.array([s[0] for s in stops], dtype=np.float64)
    stop_r = np.array([s[1][0] for s in stops], dtype=np.float64)
    stop_g = np.array([s[1][1] for s in stops], dtype=np.float64)
    stop_b = np.array([s[1][2] for s in stops], dtype=np.float64)

    norm = np.clip((values[valid_mask] - lo) / (hi - lo), 0.0, 1.0)
    r = np.round(np.interp(norm, stop_t, stop_r)).astype(np.uint8)
    g = np.round(np.interp(norm, stop_t, stop_g)).astype(np.uint8)
    b = np.round(np.interp(norm, stop_t, stop_b)).astype(np.uint8)

    rgba[valid_mask, 0] = r
    rgba[valid_mask, 1] = g
    rgba[valid_mask, 2] = b
    rgba[valid_mask, 3] = 255
    return rgba


def _slice_2d_and_spec(
    raw_arr: NDArray[np.generic],
    spec: VariableSpec,
    step_idx: int,
) -> tuple[NDArray[np.generic], VariableSpec]:
    if raw_arr.ndim < 2:
        raise UnsupportedRasterFormatError(
            f"Variable '{spec.name}' is {raw_arr.ndim}D and cannot be rendered as a 2D map raster."
        )
    arr = raw_arr
    dims = spec.dimensions
    while arr.ndim > 2:
        idx = min(step_idx, arr.shape[0] - 1) if arr.shape[0] > 0 else 0
        arr = arr[idx]
        dims = dims[1:] if len(dims) > 2 else ("y", "x")
    if len(dims) != 2:
        dims = ("y", "x")
    return arr, replace(spec, dimensions=dims)


_READER_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_RASTER_CACHE: OrderedDict[tuple[str, str], DecodedDataset] = OrderedDict()
_RASTER_CACHE_MAX_ENTRIES = 4


def _get_cached_decoded(dataset: SpatialDataset, asset: AssetReference) -> DecodedDataset | None:
    key = (str(dataset.dataset_id), asset.asset_id)
    with _CACHE_LOCK:
        cached = _RASTER_CACHE.get(key)
        if cached is not None:
            _RASTER_CACHE.move_to_end(key)
        return cached


def _put_cached_decoded(
    dataset: SpatialDataset, asset: AssetReference, decoded: DecodedDataset
) -> None:
    key = (str(dataset.dataset_id), asset.asset_id)
    with _CACHE_LOCK:
        _RASTER_CACHE[key] = decoded
        _RASTER_CACHE.move_to_end(key)
        while len(_RASTER_CACHE) > _RASTER_CACHE_MAX_ENTRIES:
            _RASTER_CACHE.popitem(last=False)


def _read_decoded_sync(
    *,
    asset: AssetReference,
    asset_path: Path | None,
    readers: ReaderRegistry,
    dataset: SpatialDataset,
) -> DecodedDataset:
    cached = _get_cached_decoded(dataset, asset)
    if cached is not None:
        return cached
    if asset_path is None:
        raise RasterAssetUnavailableError(f"Raster asset '{asset.asset_id}' path is missing.")
    # Serialize C-backed HDF4/HDF5/NetCDF reader calls across worker threads.
    with _READER_LOCK:
        cached = _get_cached_decoded(dataset, asset)
        if cached is not None:
            return cached
        if asset.data_format in ("hdf5", "netcdf") and dataset.variables:
            decoded = readers.read(asset, asset_path, variables=tuple(dataset.variables.keys()))
        else:
            decoded = readers.read(asset, asset_path)
        _put_cached_decoded(dataset, asset, decoded)
        return decoded


def _infer_fallback_grid(dataset: SpatialDataset, slice_arr: NDArray[Any]) -> GridSpec | None:
    if slice_arr.ndim < 2:
        return None
    height, width = int(slice_arr.shape[-2]), int(slice_arr.shape[-1])
    if "SPL3SMP" in dataset.product.upper() and (height, width) == (1624, 3856):
        bounds = SpatialBounds(
            -17367530.445161499, -7314540.830638599, 17367530.445161499, 7314540.830638599
        )
        return GridSpec(
            crs="EPSG:6933",
            resolution_x=34735060.890322998 / 3856.0,
            resolution_y=14629081.661277198 / 1624.0,
            resolution_unit="meter",
            bounds=bounds,
            width=3856,
            height=1624,
            pixel_convention="corner",
        ).resolved()
    b = dataset.spatial_metadata.bounds
    crs = dataset.spatial_metadata.crs
    if b is not None and crs and width > 0 and height > 0:
        return GridSpec(
            crs=crs,
            resolution_x=(b.max_x - b.min_x) / float(width),
            resolution_y=(b.max_y - b.min_y) / float(height),
            resolution_unit="degree" if "4326" in crs else "meter",
            bounds=b,
            width=width,
            height=height,
            pixel_convention="corner",
        ).resolved()
    return None


def _render_sync(
    *,
    asset: AssetReference,
    asset_path: Path | None,
    readers: ReaderRegistry,
    dataset: SpatialDataset,
    dst_bounds: SpatialBounds,
    dst_crs: str,
    width: int,
    height: int,
    step_idx: int,
    variable: str | None,
    colormap: str | None,
    vmin: float | None,
    vmax: float | None,
    unit_conversion: str | None,
) -> bytes:
    decoded = _read_decoded_sync(
        asset=asset,
        asset_path=asset_path,
        readers=readers,
        dataset=dataset,
    )
    var_name, spec = _select_raster_variable(decoded, dataset, variable)
    raw_arr = np.asarray(decoded.arrays[var_name])
    slice_arr, render_spec = _slice_2d_and_spec(raw_arr, spec, step_idx)
    src_grid = (
        spec.grid
        or decoded.grid
        or dataset.spatial_metadata.grid
        or _infer_fallback_grid(dataset, slice_arr)
    )
    if src_grid is None:
        raise IncompatibleDatasetError(f"Raster variable '{var_name}' lacks spatial grid metadata.")

    dst_grid = GridSpec(
        crs=dst_crs,
        resolution_x=(dst_bounds.max_x - dst_bounds.min_x) / float(width),
        resolution_y=(dst_bounds.max_y - dst_bounds.min_y) / float(height),
        resolution_unit="degree" if "4326" in dst_crs else "meter",
        bounds=dst_bounds,
        width=width,
        height=height,
        pixel_convention="corner",
    )

    try:
        warped, _ = warp_variable(
            slice_arr,
            render_spec,
            src_grid,
            dst_grid,
            "nearest",
            decoded.coordinates,
        )
    except (IncompatibleDatasetError, WindowError, ValueError):
        return _transparent_png(width, height)

    data = warped.data.astype(np.float64, copy=False)
    valid = np.isfinite(data)
    if render_spec.valid_range is not None:
        lo, hi = render_spec.valid_range
        valid &= (data >= lo) & (data <= hi)

    qa_var = _find_qa_variable(
        decoded, dataset.product, var_name, (slice_arr.shape[0], slice_arr.shape[1])
    )
    if qa_var is not None:
        qa_raw = np.asarray(decoded.arrays[qa_var])
        qa_slice, qa_spec = _slice_2d_and_spec(qa_raw, decoded.variables[qa_var], step_idx)
        qa_grid = qa_spec.grid or src_grid
        try:
            qa_warped, _ = warp_variable(
                qa_slice,
                replace(qa_spec, semantics="qa_flag"),
                qa_grid,
                dst_grid,
                "nearest",
                decoded.coordinates,
            )
            valid &= _evaluate_qa_mask(dataset.product, qa_warped.data, qa_var)
        except (IncompatibleDatasetError, WindowError, ValueError):
            pass

    valid_samples = data[valid]
    if _should_convert_kelvin_to_celsius(
        render_spec, dataset, colormap, unit_conversion, valid_samples
    ):
        data = np.where(valid, data - 273.15, np.nan)
        valid &= np.isfinite(data) & (data >= -100.0) & (data <= 80.0)

    ramp_name = colormap or "viridis"
    rgba = _colorize_values(data, valid, colormap=ramp_name, vmin=vmin, vmax=vmax)
    return encode_rgba_png(rgba)


async def render_dataset_tile(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    z: int,
    x: int,
    y: int,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> bytes:
    """Render an XYZ 256x256 PNG tile for a persisted raster dataset."""
    candidates = _select_candidate_raster_assets(dataset, timestamp=timestamp, variable=variable)
    tile_3857 = tile_bounds_3857(z, x, y)
    ds_wgs84 = _dataset_wgs84_bounds(dataset)
    if ds_wgs84 is not None:
        ds_3857 = tuple(
            float(v) for v in transform_bounds("EPSG:4326", "EPSG:3857", *ds_wgs84, densify_pts=21)
        )
        if not _bounds_intersect(tile_3857, (ds_3857[0], ds_3857[1], ds_3857[2], ds_3857[3])):
            return _transparent_png(256, 256)

    dst_bounds = SpatialBounds(*tile_3857)
    last_exc: Exception | None = None
    for asset, step_idx in candidates:
        if _get_cached_decoded(dataset, asset) is not None:
            try:
                return await asyncio.to_thread(
                    _render_sync,
                    asset=asset,
                    asset_path=None,
                    readers=readers,
                    dataset=dataset,
                    dst_bounds=dst_bounds,
                    dst_crs="EPSG:3857",
                    width=256,
                    height=256,
                    step_idx=step_idx,
                    variable=variable,
                    colormap=colormap,
                    vmin=vmin,
                    vmax=vmax,
                    unit_conversion=unit_conversion,
                )
            except Exception as exc:
                last_exc = exc
                continue

        with tempfile.TemporaryDirectory(prefix="ghs-tile-", dir=_scratch_base()) as tmp_root:
            try:
                handle = await _materialize_asset(asset, storage, Path(tmp_root))
            except (RasterAssetUnavailableError, FileNotFoundError, OSError) as exc:
                last_exc = exc
                continue
            try:
                return await asyncio.to_thread(
                    _render_sync,
                    asset=asset,
                    asset_path=handle.path,
                    readers=readers,
                    dataset=dataset,
                    dst_bounds=dst_bounds,
                    dst_crs="EPSG:3857",
                    width=256,
                    height=256,
                    step_idx=step_idx,
                    variable=variable,
                    colormap=colormap,
                    vmin=vmin,
                    vmax=vmax,
                    unit_conversion=unit_conversion,
                )
            except Exception as exc:
                last_exc = exc
                continue
            finally:
                handle.release()

    if last_exc:
        raise last_exc
    raise RasterAssetUnavailableError(
        f"No usable raster assets available for dataset '{dataset.dataset_id}'."
    )


async def render_dataset_bbox(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    bbox: tuple[float, float, float, float],
    crs: str = "EPSG:4326",
    width: int = 512,
    height: int = 512,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> bytes:
    """Render a georeferenced RGBA PNG image for a bounding box over a raster dataset."""
    candidates = _select_candidate_raster_assets(dataset, timestamp=timestamp, variable=variable)
    dst_bounds = SpatialBounds(*bbox)
    last_exc: Exception | None = None
    for asset, step_idx in candidates:
        with tempfile.TemporaryDirectory(prefix="ghs-bbox-", dir=_scratch_base()) as tmp_root:
            try:
                handle = await _materialize_asset(asset, storage, Path(tmp_root))
            except (RasterAssetUnavailableError, FileNotFoundError, OSError) as exc:
                last_exc = exc
                continue
            try:
                return await asyncio.to_thread(
                    _render_sync,
                    asset=asset,
                    asset_path=handle.path,
                    readers=readers,
                    dataset=dataset,
                    dst_bounds=dst_bounds,
                    dst_crs=crs,
                    width=width,
                    height=height,
                    step_idx=step_idx,
                    variable=variable,
                    colormap=colormap,
                    vmin=vmin,
                    vmax=vmax,
                    unit_conversion=unit_conversion,
                )
            except Exception as exc:
                last_exc = exc
                continue
            finally:
                handle.release()

    if last_exc:
        raise last_exc
    raise RasterAssetUnavailableError(
        f"No usable raster assets available for dataset '{dataset.dataset_id}'."
    )


def _evaluate_qa_pass(product: str, qa_code: float | int, qa_var_name: str = "") -> bool | None:
    if isinstance(qa_code, float) and not math.isfinite(qa_code):
        return False
    upper = product.upper()
    if "IMERG" in upper:
        return float(qa_code) >= 0.5
    qa_int = int(qa_code)
    if "MOD13" in upper:
        if "vi quality" in qa_var_name.lower():
            return (qa_int & 0b11) <= 1
        return qa_int in (0, 1)
    if "MOD11" in upper:
        mandatory = qa_int & 0b11
        err_bits = (qa_int >> 6) & 0b11
        return mandatory <= 1 and err_bits <= 1
    if "SPL3SMP" in upper:
        return qa_int >= 0 and (qa_int & 0b1) == 0
    return None


def _point_query_sync(
    *,
    asset: AssetReference,
    asset_path: Path | None,
    readers: ReaderRegistry,
    dataset: SpatialDataset,
    lon: float,
    lat: float,
    step_idx: int,
    variable: str | None,
    timestamp: str | None,
    unit_conversion: str | None,
) -> dict[str, Any]:
    decoded = _read_decoded_sync(
        asset=asset,
        asset_path=asset_path,
        readers=readers,
        dataset=dataset,
    )
    var_name, spec = _select_raster_variable(decoded, dataset, variable)
    raw_arr = np.asarray(decoded.arrays[var_name])
    slice_arr, slice_spec = _slice_2d_and_spec(raw_arr, spec, step_idx)
    src_grid = (
        spec.grid
        or decoded.grid
        or dataset.spatial_metadata.grid
        or _infer_fallback_grid(dataset, slice_arr)
    )
    if src_grid is None:
        raise IncompatibleDatasetError(f"Raster variable '{var_name}' lacks spatial grid metadata.")
    oriented, _ = orient_to_north_up(slice_arr, slice_spec.dimensions, decoded.coordinates)
    src_res = src_grid.resolved()
    aff = to_rasterio_affine(src_res)

    if "4326" in src_res.crs:
        x_nat, y_nat = lon, lat
    else:
        tx = Transformer.from_crs("EPSG:4326", src_res.crs, always_xy=True)
        x_nat, y_nat = tx.transform(lon, lat)

    col_f, row_f = (~aff) @ (x_nat, y_nat)
    col, row = math.floor(col_f), math.floor(row_f)

    ds_bbox = _dataset_wgs84_bounds(dataset) or (-180.0, -90.0, 180.0, 90.0)
    ts_list = _extract_timestamps_list(dataset, var_name)
    fallback_ts = dataset.temporal_metadata.start.isoformat()
    active_ts = timestamp or (ts_list[step_idx] if step_idx < len(ts_list) else fallback_ts)

    convert_to_celsius = _should_convert_kelvin_to_celsius(spec, dataset, None, unit_conversion)

    time_series_pts: list[dict[str, Any]] = []
    ts_ext = dataset.extensions.get("time_series")
    if isinstance(ts_ext, Mapping):
        ts_entry = ts_ext.get(var_name)
        if ts_entry is None:
            for k, v in ts_ext.items():
                if _match_variable_name([str(k)], var_name) or _match_variable_name(
                    [var_name], str(k)
                ):
                    ts_entry = v
                    break
        if ts_entry is None and len(ts_ext) == 1:
            ts_entry = next(iter(ts_ext.values()))
        if isinstance(ts_entry, Mapping):
            e_ts = ts_entry.get("timestamps") or []
            e_vals = ts_entry.get("values") or []
            for t_str, t_val in zip(e_ts, e_vals, strict=False):
                out_ts_val: float | None = None
                if isinstance(t_val, (int, float)) and math.isfinite(float(t_val)):
                    v_num = float(t_val)
                    if convert_to_celsius and v_num > 120.0:
                        v_num -= 273.15
                    out_ts_val = v_num
                time_series_pts.append({"timestamp": str(t_str), "value": out_ts_val})

    unit_out = "°C" if convert_to_celsius else dataset.units.get(var_name, spec.units)
    base_resp: dict[str, Any] = {
        "dataset_id": dataset.dataset_id,
        "product": dataset.product,
        "variable": var_name,
        "lon": lon,
        "lat": lat,
        "timestamp": active_ts,
        "crs": src_res.crs,
        "nominal_resolution_m": (
            float(src_res.resolution_x) if "4326" not in src_res.crs else None
        ),
        "bbox": {
            "min_lon": ds_bbox[0],
            "min_lat": ds_bbox[1],
            "max_lon": ds_bbox[2],
            "max_lat": ds_bbox[3],
        },
        "time_series": time_series_pts,
    }

    if row < 0 or row >= oriented.shape[0] or col < 0 or col >= oriented.shape[1]:
        return {
            **base_resp,
            "status": "outside_bounds",
            "value": None,
            "raw_value": None,
            "unit": unit_out,
            "qa_value": None,
            "qa_passed": None,
            "pixel_row": None,
            "pixel_col": None,
        }

    raw_scalar = float(oriented[row, col])
    qa_var = _find_qa_variable(
        decoded, dataset.product, var_name, (oriented.shape[0], oriented.shape[1])
    )
    qa_val: int | None = None
    qa_passed: bool | None = None
    if qa_var is not None:
        qa_raw = np.asarray(decoded.arrays[qa_var])
        qa_slice, qa_spec = _slice_2d_and_spec(qa_raw, decoded.variables[qa_var], step_idx)
        qa_oriented, _ = orient_to_north_up(qa_slice, qa_spec.dimensions, decoded.coordinates)
        qa_scalar = float(qa_oriented[row, col])
        if math.isfinite(qa_scalar):
            qa_val = round(qa_scalar)
            qa_passed = _evaluate_qa_pass(dataset.product, qa_scalar, qa_var)
        else:
            qa_passed = False

    is_nodata = not math.isfinite(raw_scalar)
    if not is_nodata and spec.nodata is not None:
        nd = float(spec.nodata)
        is_nodata = math.isnan(nd) if math.isnan(raw_scalar) else raw_scalar == nd

    if is_nodata:
        return {
            **base_resp,
            "status": "nodata",
            "value": None,
            "raw_value": raw_scalar if math.isfinite(raw_scalar) else None,
            "unit": unit_out,
            "qa_value": qa_val,
            "qa_passed": qa_passed,
            "pixel_row": row,
            "pixel_col": col,
        }

    if qa_passed is False:
        return {
            **base_resp,
            "status": "nodata",
            "value": None,
            "raw_value": raw_scalar,
            "unit": unit_out,
            "qa_value": qa_val,
            "qa_passed": False,
            "pixel_row": row,
            "pixel_col": col,
        }

    scale = spec.scale_factor if spec.scale_factor is not None else 1.0
    offset = spec.add_offset if spec.add_offset is not None else 0.0
    phys = raw_scalar * scale + offset

    if not math.isfinite(phys):
        return {
            **base_resp,
            "status": "nodata",
            "value": None,
            "raw_value": raw_scalar,
            "unit": unit_out,
            "qa_value": qa_val,
            "qa_passed": qa_passed,
            "pixel_row": row,
            "pixel_col": col,
        }

    if spec.valid_range is not None:
        lo, hi = spec.valid_range
        if phys < lo or phys > hi:
            return {
                **base_resp,
                "status": "nodata",
                "value": None,
                "raw_value": raw_scalar,
                "unit": unit_out,
                "qa_value": qa_val,
                "qa_passed": qa_passed,
                "pixel_row": row,
                "pixel_col": col,
            }

    if convert_to_celsius and _should_convert_kelvin_to_celsius(
        spec, dataset, None, unit_conversion, np.array([phys], dtype=np.float64)
    ):
        phys -= 273.15
        unit_out = "°C"
        if phys < -100.0 or phys > 80.0:
            return {
                **base_resp,
                "status": "nodata",
                "value": None,
                "raw_value": raw_scalar,
                "unit": unit_out,
                "qa_value": qa_val,
                "qa_passed": qa_passed,
                "pixel_row": row,
                "pixel_col": col,
            }

    return {
        **base_resp,
        "status": "ok",
        "value": float(phys),
        "raw_value": raw_scalar,
        "unit": unit_out,
        "qa_value": qa_val,
        "qa_passed": qa_passed,
        "pixel_row": row,
        "pixel_col": col,
    }


async def query_dataset_point(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    lon: float,
    lat: float,
    variable: str | None = None,
    timestamp: str | None = None,
    unit_conversion: str | None = None,
) -> dict[str, Any]:
    """Sample exact native grid pixel value and QA metadata at WGS 84 (lon, lat)."""
    candidates = _select_candidate_raster_assets(dataset, timestamp=timestamp, variable=variable)
    last_exc: Exception | None = None
    for asset, step_idx in candidates:
        with tempfile.TemporaryDirectory(prefix="ghs-pt-", dir=_scratch_base()) as tmp_root:
            try:
                handle = await _materialize_asset(asset, storage, Path(tmp_root))
            except (RasterAssetUnavailableError, FileNotFoundError, OSError) as exc:
                last_exc = exc
                continue
            try:
                return await asyncio.to_thread(
                    _point_query_sync,
                    asset=asset,
                    asset_path=handle.path,
                    readers=readers,
                    dataset=dataset,
                    lon=lon,
                    lat=lat,
                    step_idx=step_idx,
                    variable=variable,
                    timestamp=timestamp,
                    unit_conversion=unit_conversion,
                )
            except Exception as exc:
                last_exc = exc
                continue
            finally:
                handle.release()

    if last_exc:
        raise last_exc
    raise RasterAssetUnavailableError(
        f"No usable raster assets available for dataset '{dataset.dataset_id}'."
    )
