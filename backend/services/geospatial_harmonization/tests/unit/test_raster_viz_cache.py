"""Unit tests for the bounded, concurrency-safe materialized-asset cache in raster_viz."""

import os
from pathlib import Path

import pytest

from geospatial_harmonization.application import raster_viz
from geospatial_harmonization.domain.models.dataset import AssetReference


class _FakeStorage:
    """Minimal StoragePort double counting materialize calls."""

    def __init__(self, size_bytes: int) -> None:
        self._size_bytes = size_bytes
        self.materialize_calls = 0

    async def head_object(self, key: str):
        return type("Info", (), {"size_bytes": self._size_bytes})()

    async def materialize_to_path(self, key: str, dest: Path) -> Path:
        self.materialize_calls += 1
        dest.write_bytes(b"\0" * self._size_bytes)
        return dest


def _asset(storage_key: str = "derived/test.tif", size_bytes: int | None = None) -> AssetReference:
    return AssetReference(
        asset_id=storage_key,
        uri=f"file:///data/{storage_key}",
        data_format="geotiff",
        media_type="image/tiff",
        storage_key=storage_key,
        size_bytes=size_bytes,
        checksum_sha256=None,
    )


@pytest.fixture(autouse=True)
def _temp_scratch_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from geospatial_harmonization.config.settings import Settings
    from geospatial_harmonization.storage import scratch

    cfg = Settings(_env_file=None, environment="test", ghs_storage_temp_dir=tmp_path)
    monkeypatch.setattr(scratch, "get_settings", lambda: cfg)
    raster_viz._ASSET_CACHE_MAX_BYTES = 256 * 1024
    raster_viz._MAX_CACHEABLE_ASSET_BYTES = 128 * 1024
    raster_viz._ASSET_CACHE_ENTRIES.clear()
    raster_viz._ASSET_CACHE_IN_USE.clear()
    raster_viz._ASSET_CACHE_EVICTION_PENDING.clear()
    raster_viz._ASSET_CACHE_TOTAL_BYTES = 0
    raster_viz._CACHE_SWEEP_DONE = True
    yield cfg
    raster_viz._ASSET_CACHE_ENTRIES.clear()
    raster_viz._ASSET_CACHE_IN_USE.clear()
    raster_viz._ASSET_CACHE_EVICTION_PENDING.clear()
    raster_viz._ASSET_CACHE_TOTAL_BYTES = 0
    raster_viz._ASSET_CACHE_MAX_BYTES = 256 * 1024 * 1024
    raster_viz._MAX_CACHEABLE_ASSET_BYTES = 128 * 1024 * 1024


async def test_oversized_asset_not_cached_but_materialized_once(tmp_path: Path) -> None:
    """Assets larger than the cache threshold skip the cache and are not re-downloaded."""
    storage = _FakeStorage(size_bytes=512 * 1024)  # > half of the 256 KiB cache budget
    asset = _asset(size_bytes=512 * 1024)
    request_dir = tmp_path / "req"
    request_dir.mkdir()

    handle = await raster_viz._materialize_asset(asset, storage, request_dir)
    try:
        stored_path = handle.path
        assert stored_path.is_file()
        assert stored_path.parent == request_dir, (
            "oversized asset must materialize inside the request scratch dir"
        )
        assert storage.materialize_calls == 1
    finally:
        handle.release()
    assert raster_viz._ASSET_CACHE_ENTRIES == {}, "oversized asset must not enter the cache"
    assert raster_viz._ASSET_CACHE_TOTAL_BYTES == 0
    cache_dir = raster_viz._resolve_cache_dir()
    if cache_dir.is_dir():
        assert list(cache_dir.iterdir()) == [], "cache dir must stay empty"


async def test_cacheable_asset_is_cached_and_checked_out_concurrently(tmp_path: Path) -> None:
    storage = _FakeStorage(size_bytes=1024)
    asset = _asset(size_bytes=1024)
    request_dir = tmp_path / "req"
    request_dir.mkdir()

    handle1 = await raster_viz._materialize_asset(asset, storage, request_dir)
    assert handle1.cache_key is not None
    assert storage.materialize_calls == 1

    handle2 = await raster_viz._materialize_asset(asset, storage, request_dir)
    assert storage.materialize_calls == 1, "second request must reuse the cached file"
    assert handle2.path == handle1.path

    handle1.release()
    handle2.release()
    assert raster_viz._ASSET_CACHE_TOTAL_BYTES == 1024


async def test_unknown_size_asset_single_download_no_double_materialization(
    tmp_path: Path,
) -> None:
    """When metadata lacks size, only one materialization occurs (no retry on oversize)."""
    storage = _FakeStorage(size_bytes=1024)
    asset = _asset(size_bytes=None)
    request_dir = tmp_path / "req"
    request_dir.mkdir()

    handle = await raster_viz._materialize_asset(asset, storage, request_dir)
    assert storage.materialize_calls == 1
    handle.release()
    assert raster_viz._ASSET_CACHE_TOTAL_BYTES == 1024  # small -> cached


async def test_eviction_skips_in_use_entries_under_concurrency(tmp_path: Path) -> None:
    storage_small = _FakeStorage(size_bytes=1024)
    assets = [_asset(f"derived/test-{i}.tif", 1024) for i in range(4)]
    request_dir = tmp_path / "req"
    request_dir.mkdir()

    handles = [await raster_viz._materialize_asset(a, storage_small, request_dir) for a in assets]
    keys = [h.cache_key for h in handles]
    assert all(k is not None for k in keys)

    checked_path = handles[0].path
    for h in handles[1:]:
        h.release()

    # Force the cache over budget; all entries beyond budget should evict.
    raster_viz._ASSET_CACHE_MAX_BYTES = 1024
    raster_viz._evict_asset_cache_if_needed()
    try:
        assert checked_path.exists(), "checked-out cache entry must survive eviction"
    finally:
        for key in keys:
            if key is not None:
                raster_viz._ASSET_CACHE_IN_USE.pop(key, None)
        handles[0].release()
        raster_viz._ASSET_CACHE_ENTRIES.clear()
        raster_viz._ASSET_CACHE_TOTAL_BYTES = 0


def test_sweep_removes_cache_files_of_dead_processes_and_keeps_live(tmp_path: Path) -> None:
    cache_dir = raster_viz._resolve_cache_dir()
    cache_dir.mkdir(parents=True)
    dead_file = cache_dir / f"a{os.getpid():023x}.{2**22}.hint.tif"  # dead pid, real key shape
    dead_file.write_bytes(b"stale")
    live_file = cache_dir / f"b{os.getpid():023x}.{os.getpid()}.hint.tif"
    live_file.write_bytes(b"keep")

    raster_viz._CACHE_SWEEP_DONE = False
    raster_viz._sweep_stale_cache_entries()

    assert not dead_file.exists()
    assert live_file.exists()
