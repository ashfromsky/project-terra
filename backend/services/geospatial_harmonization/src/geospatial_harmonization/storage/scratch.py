"""Unified scratch (temporary) directory management for all GHS components.

Every GHS subsystem that needs scratch space — provider handler ingestion,
harmonization execution, raster materialization, tile/bbox/point rendering,
and transformation output — resolves its base directory through this module
so that ``GHS_STORAGE_TEMP_DIR`` is honored consistently instead of some
components falling back to the system temp directory.

Scratch directories created here carry an ownership marker (``.ghs_scratch_owner.json``)
recording the creating process and timestamp. The janitor sweep removes
directories owned by dead processes and unmarked leftovers past a conservative
age threshold, so both failed-ingestion artifacts and directories abandoned by
SIGKILL/OOM are reclaimed after normal exceptions and after process restarts.
"""

import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.config.settings import get_settings as get_settings

__all__ = ["Settings", "get_settings"]
from geospatial_harmonization.domain.exceptions import ScratchCapacityError

logger = logging.getLogger(__name__)

SCRATCH_MARKER_NAME = ".ghs_scratch_owner.json"

# Sizes below this threshold skip the aggregate-usage scan; stat-ing a large
# scratch tree on every small write would dominate the request path.
_CAPACITY_CHECK_FLOOR_BYTES = 32 * 1024 * 1024
_USAGE_CACHE_TTL_SECONDS = 30


def scratch_base_dir(settings: Settings | None = None) -> Path:
    """Return the effective scratch base directory, creating a configured one.

    The configured ``GHS_STORAGE_TEMP_DIR`` is honored the same way by handler
    ingestion, harmonization, rendering, and grid transforms.
    """
    cfg = settings or get_settings()
    base = cfg.ghs_storage_temp_dir
    if base is None or not str(base).strip():
        return Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _is_pid_alive(pid: int) -> bool:
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
        # OverflowError: pid outside the OS pid range cannot name a live process.
        return False
    return True


def _read_marker(dir_path: Path) -> dict[str, object] | None:
    marker = dir_path / SCRATCH_MARKER_NAME
    try:
        loaded: object = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def create_scratch_dir(settings: Settings | None, prefix: str) -> Path:
    """Create an isolated, marker-stamped scratch directory for one operation."""
    base = scratch_base_dir(settings)
    dir_path = Path(tempfile.mkdtemp(prefix=prefix, dir=base))
    marker = {
        "pid": os.getpid(),
        "created_at": datetime.now(UTC).isoformat(),
        "prefix": prefix,
    }
    with contextlib.suppress(OSError):
        (dir_path / SCRATCH_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
    return dir_path


def remove_scratch_dir(path: Path, *, allow_missing: bool = True) -> bool:
    """Remove a scratch directory owned by this module, conservatively.

    Refuses paths that do not carry the ownership marker and are not named
    ``ghs_*``, so unrelated directories can never be deleted through this helper.
    """
    if not path.is_dir():
        return allow_missing
    if not _read_marker(path) and not path.name.startswith("ghs_"):
        logger.warning("Refusing to remove unmarked scratch directory %s", path)
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def sweep_stale_scratch(
    settings: Settings | None = None,
    *,
    max_age_seconds: int | None = None,
    cache_dirs: tuple[str, ...] = ("ghs_raster_cache",),
) -> tuple[int, int]:
    """Remove scratch directories and temp files abandoned by dead processes.

    Returns ``(removed_dirs, removed_files)``. Directories owned by a live
    process are never touched, and unmarked entries are only removed once
    their modification age exceeds ``max_age_seconds``.
    """
    cfg = settings or get_settings()
    base = cfg.ghs_storage_temp_dir
    if base is None or not base.is_dir():
        return (0, 0)
    age_limit = max_age_seconds or cfg.ghs_storage_abandoned_temp_max_age_seconds
    now = time.time()
    removed_dirs = 0
    removed_files = 0
    scan_roots: list[Path] = [base]
    scan_roots.extend(base / cache_dir for cache_dir in cache_dirs if (base / cache_dir).is_dir())
    for root in scan_roots:
        try:
            with os.scandir(root) as entries:
                listing = list(entries)
        except OSError:
            continue
        for entry in listing:
            dir_path = Path(entry.path).resolve()
            if not dir_path.is_relative_to(base.resolve()) or dir_path == base.resolve():
                continue
            if entry.is_dir(follow_symlinks=False):
                if _remove_if_abandoned_dir(dir_path, now, age_limit):
                    removed_dirs += 1
                continue
            if not entry.name.startswith(".") and not entry.name.startswith("ghs_"):
                continue
            if now - entry.stat().st_mtime > age_limit:
                with contextlib.suppress(OSError):
                    Path(entry.path).unlink(missing_ok=True)
                    removed_files += 1
    return (removed_dirs, removed_files)


def _remove_if_abandoned_dir(dir_path: Path, now: float, age_limit: int) -> bool:
    marker = _read_marker(dir_path)
    if marker is not None:
        raw_pid = marker.get("pid")
        owner_pid = -1
        if isinstance(raw_pid, int) and not isinstance(raw_pid, bool):
            owner_pid = raw_pid
        if _is_pid_alive(owner_pid):
            return False
        shutil.rmtree(dir_path, ignore_errors=True)
        return True
    # Unmarked legacy layout (system mkdtemp redirected under the scratch base,
    # or partial directory creation): only age-based reclamation is safe.
    try:
        mtime = dir_path.stat().st_mtime
    except OSError:
        return False
    if now - mtime <= age_limit:
        return False
    shutil.rmtree(dir_path, ignore_errors=True)
    return True


def _usage_bytes_excluding_cache(base: Path, cache_dirs: tuple[str, ...]) -> int:
    cache_names = set(cache_dirs)
    total = 0
    try:
        stack = [base]
        while stack:
            current = stack.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in cache_names:
                                stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
    except OSError:
        return total
    return total


_usage_cache: tuple[float, int, str | None] = (0.0, 0, None)


def _cached_scratch_usage(base: Path) -> int:
    global _usage_cache
    cache_dirs: tuple[str, ...] = ("ghs_raster_cache",)
    key = str(base)
    stamp, value, cached_key = _usage_cache
    now = time.monotonic()
    if cached_key == key and now - stamp < _USAGE_CACHE_TTL_SECONDS:
        return value
    total = _usage_bytes_excluding_cache(base, cache_dirs)
    _usage_cache = (now, total, key)
    return total


def check_scratch_capacity(settings: Settings | None, required_bytes: int) -> None:
    """Raise :class:`ScratchCapacityError` when a scratch write cannot succeed.

    Checks the configured aggregate scratch budget (``ghs_storage_temp_max_bytes``)
    for configured scratch roots and the filesystem free space visible to the
    current user. This is best-effort against per-user filesystem quotas; when a
    quota is smaller than free space, the resulting ENOSPC/EDQUOT write error is
    translated into the same non-retryable :class:`ScratchCapacityError`.
    """
    cfg = settings or get_settings()
    temp_base = cfg.ghs_storage_temp_dir
    cap = cfg.ghs_storage_temp_max_bytes
    if temp_base is not None and required_bytes > 0:
        base = scratch_base_dir(cfg)
        usage = _cached_scratch_usage(base)
        headroom = max(0, cap - usage)
        if required_bytes > headroom:
            raise ScratchCapacityError(
                f"Scratch directory '{temp_base}' usage {usage} B leaves only "
                f"{headroom} B under the configured budget {cap} B; refusing "
                f"allocation of {required_bytes} B",
                requested_bytes=required_bytes,
                available_bytes=headroom,
            )
    if required_bytes <= _CAPACITY_CHECK_FLOOR_BYTES or temp_base is None:
        # Tiny ephemeral writes do not justify a statvfs on every request; when
        # they hit an actual quota boundary the write fails and the OSError
        # translation in the caller raises the same ScratchCapacityError.
        return
    try:
        free = shutil.disk_usage(str(scratch_base_dir(cfg))).free
    except OSError:
        return
    if required_bytes > free:
        raise ScratchCapacityError(
            f"Insufficient scratch disk space on '{scratch_base_dir(cfg)}' "
            f"({free} B free < {required_bytes} B required)",
            requested_bytes=required_bytes,
            available_bytes=free,
        )


async def run_with_owned_base_dir[T](
    run: Callable[[Path], Awaitable[T]],
    *,
    settings: Settings,
    prefix: str,
    raw_dir: Path | None,
) -> T:
    """Run an operation with a base directory owned by the caller when needed.

    When ``raw_dir`` is provided the operation runs inside it unchanged. When it
    is ``None`` a fresh scratch directory is created under the unified scratch
    base and removed again if the operation raises, so failed handler ingestion
    does not leave directory debris behind; on success the directory survives so
    the caller can persist assets from it (harmonization removes it in its
    ``finally`` block).
    """
    if raw_dir is not None:
        return await run(raw_dir)
    base_dir = create_scratch_dir(settings, prefix)
    try:
        return await run(base_dir)
    except BaseException:
        remove_scratch_dir(base_dir)
        raise
