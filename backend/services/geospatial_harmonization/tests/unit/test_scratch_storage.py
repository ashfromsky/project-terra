"""Unit tests for the unified GHS scratch directory, janitor sweep, and capacity guards."""

import errno
import json
import os
from pathlib import Path

import pytest

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain import exceptions as dom_exc
from geospatial_harmonization.domain.exceptions import (
    ScratchCapacityError,
    classify_exception,
)
from geospatial_harmonization.storage.scratch import (
    SCRATCH_MARKER_NAME,
    check_scratch_capacity,
    create_scratch_dir,
    remove_scratch_dir,
    run_with_owned_base_dir,
    scratch_base_dir,
    sweep_stale_scratch,
)


def _settings_with_temp(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        ghs_storage_temp_dir=tmp_path,
        **overrides,
    )


def test_scratch_base_dir_creates_and_uses_configured_dir(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path / "scratch")
    base = scratch_base_dir(cfg)
    assert base == tmp_path / "scratch"
    assert base.is_dir()


def test_create_scratch_dir_writes_ownership_marker(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)
    dir_path = create_scratch_dir(cfg, prefix="ghs_test_")
    try:
        assert dir_path.parent == tmp_path
        assert dir_path.name.startswith("ghs_test_")
        marker = json.loads((dir_path / SCRATCH_MARKER_NAME).read_text(encoding="utf-8"))
        assert marker["pid"] == os.getpid()
    finally:
        remove_scratch_dir(dir_path)
    assert not dir_path.exists()


async def test_run_with_owned_base_dir_uses_given_raw_dir(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)
    given = tmp_path / "given-raw"
    given.mkdir()

    async def run(base_dir: Path) -> Path:
        return base_dir

    result = await run_with_owned_base_dir(run, settings=cfg, prefix="ghs_t_", raw_dir=given)
    assert result == given
    assert list(tmp_path.iterdir()) == [given]


async def test_run_with_owned_base_dir_removes_dir_on_failure(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)

    async def fail(base_dir: Path) -> Path:
        assert base_dir.is_dir()
        (base_dir / "partial.tif").write_bytes(b"x")
        raise RuntimeError("ingestion failed")

    with pytest.raises(RuntimeError):
        await run_with_owned_base_dir(fail, settings=cfg, prefix="ghs_t_", raw_dir=None)
    assert list(tmp_path.iterdir()) == []


async def test_run_with_owned_base_dir_keeps_dir_for_caller_on_success(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)

    async def succeed(base_dir: Path) -> Path:
        (base_dir / "asset.tif").write_bytes(b"x")
        return base_dir

    result = await run_with_owned_base_dir(succeed, settings=cfg, prefix="ghs_t_", raw_dir=None)
    assert result.is_dir()
    assert (result / "asset.tif").read_bytes() == b"x"
    remove_scratch_dir(result, allow_missing=True)


def test_sweep_removes_dead_pid_dirs_and_keeps_live_ones(tmp_path: Path) -> None:
    dead_dir = create_scratch_dir(_settings_with_temp(tmp_path), prefix="ghs_dead_")
    marker = json.loads((dead_dir / SCRATCH_MARKER_NAME).read_text(encoding="utf-8"))
    marker["pid"] = 2**22  # above typical pid_max, guaranteed dead, valid for os.kill
    (dead_dir / SCRATCH_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")

    live_dir = create_scratch_dir(_settings_with_temp(tmp_path), prefix="ghs_live_")

    removed_dirs, _ = sweep_stale_scratch(_settings_with_temp(tmp_path), max_age_seconds=1)

    assert removed_dirs == 1
    assert not dead_dir.exists()
    assert live_dir.exists()
    remove_scratch_dir(live_dir, allow_missing=True)


def test_sweep_keeps_fresh_unmarked_dir_and_removes_old_one(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)
    base = scratch_base_dir(cfg)
    old_unmarked = Path(os.path.join(str(base), "ghs_legacy_unmarked"))
    old_unmarked.mkdir()
    os.utime(old_unmarked, (1_000_000_000, 1_000_000_000))

    removed_dirs, _ = sweep_stale_scratch(cfg, max_age_seconds=1)
    assert removed_dirs >= 1
    assert not old_unmarked.exists()


def test_sweep_ignores_unrelated_files(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)
    base = scratch_base_dir(cfg)
    unrelated = base / "important_data"
    unrelated.write_bytes(b"keep me")
    os.utime(unrelated, (1_000_000_000, 1_000_000_000))

    sweep_stale_scratch(cfg, max_age_seconds=1)
    assert unrelated.exists()


def test_check_scratch_capacity_enforces_configured_cap(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path, ghs_storage_temp_max_bytes=1_048_576)
    base = scratch_base_dir(cfg)
    (base / "ghs_blob").write_bytes(b"\0" * 900_000)

    with pytest.raises(ScratchCapacityError):
        check_scratch_capacity(cfg, 2 * 1_048_576)
    check_scratch_capacity(None, 1_000)


def test_capacity_check_skip_small_without_violation(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path, ghs_storage_temp_max_bytes=1_048_576)
    check_scratch_capacity(cfg, 1_000)  # below floor: no scan, no error


@pytest.mark.parametrize("err_no", [errno.ENOSPC, errno.EDQUOT])
def test_capacity_oseerrors_are_non_retryable_storage(err_no: int) -> None:
    exc = OSError(err_no, os.strerror(err_no))
    category, retryable = classify_exception(exc)
    assert category == "storage"
    assert retryable is False


def test_generic_oserror_stays_retryable_unknown() -> None:
    category, retryable = classify_exception(OSError(errno.EIO, "io error"))
    assert category == "unknown"
    assert retryable is True


def test_scratch_capacity_error_helpers() -> None:
    translated = dom_exc.scratch_capacity_error_from_oserror(
        OSError(errno.ENOSPC, "No space left on device")
    )
    assert isinstance(translated, ScratchCapacityError)
    assert translated.os_errno == errno.ENOSPC
    assert dom_exc.scratch_capacity_error_from_oserror(OSError(errno.EIO, "io")) is None


def test_concurrent_scratch_dirs_do_not_collide(tmp_path: Path) -> None:
    cfg = _settings_with_temp(tmp_path)
    dirs = {create_scratch_dir(cfg, prefix="ghs_par_") for _ in range(8)}
    assert len(dirs) == 8
    for d in dirs:
        remove_scratch_dir(d, allow_missing=True)


async def test_eviction_never_removes_checked_out_entry(tmp_path: Path) -> None:
    from geospatial_harmonization.application import raster_viz

    raster_viz._ASSET_CACHE_ENTRIES.clear()
    raster_viz._ASSET_CACHE_IN_USE.clear()
    raster_viz._ASSET_CACHE_TOTAL_BYTES = 0

    original_max = raster_viz._ASSET_CACHE_MAX_BYTES
    raster_viz._ASSET_CACHE_MAX_BYTES = 10
    try:
        entry_a = tmp_path / "a.bin"
        entry_a.write_bytes(b"x" * 6)
        entry_b = tmp_path / "b.bin"
        entry_b.write_bytes(b"y" * 6)

        raster_viz._ASSET_CACHE_ENTRIES["a"] = (entry_a, 6)
        raster_viz._ASSET_CACHE_TOTAL_BYTES = 6

        # Check out "a" (in use) then insert an entry that pushes over budget.
        checked_out = raster_viz._checkout_cached("a")
        assert checked_out == entry_a
        raster_viz._ASSET_CACHE_ENTRIES["b"] = (entry_b, 6)
        raster_viz._ASSET_CACHE_TOTAL_BYTES = 12

        raster_viz._evict_asset_cache_if_needed()
        assert entry_a.exists(), "in-use cached file must not be evicted"
        assert "a" in raster_viz._ASSET_CACHE_ENTRIES

        raster_viz._checkin_cached("a")
        raster_viz._evict_asset_cache_if_needed()
        assert raster_viz._ASSET_CACHE_TOTAL_BYTES <= raster_viz._ASSET_CACHE_MAX_BYTES
    finally:
        raster_viz._ASSET_CACHE_MAX_BYTES = original_max
        raster_viz._ASSET_CACHE_ENTRIES.clear()
        raster_viz._ASSET_CACHE_IN_USE.clear()
        raster_viz._ASSET_CACHE_TOTAL_BYTES = 0
