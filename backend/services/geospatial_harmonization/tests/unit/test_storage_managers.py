"""Unit tests for StorageQuotaManager, ContentDeduplicationService, Lifecycle & Monitoring."""

import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import (
    StorageBudgetExceededError,
    StorageImmutabilityError,
    StorageIntegrityError,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    StorageUsageMetricsSnapshot,
    ZoneUsageSummary,
)
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    GhsStorageAssetRefModel,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.storage import LocalObjectStore
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository
from geospatial_harmonization.storage.dedup import ContentDeduplicationService, compute_file_sha256
from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
from geospatial_harmonization.storage.monitoring import StorageMonitoringService
from geospatial_harmonization.storage.quota import StorageQuotaManager
from geospatial_harmonization.storage.zones import StorageZoneManager


def _make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "local_storage_dir": tmp_path / "datalake",
        "ghs_storage_budget_bytes": 10_000,
        "ghs_storage_warning_threshold": 0.80,
        "ghs_storage_hard_limit_threshold": 1.00,
        "ghs_storage_max_object_bytes": 5_000,
        "ghs_storage_max_job_output_bytes": 4_000,
        "ghs_storage_reservation_ttl_seconds": 60,
        "ghs_storage_intermediate_retention_seconds": 60,
        "ghs_storage_orphan_grace_seconds": 300,
        "ghs_storage_abandoned_temp_max_age_seconds": 60,
        "ghs_storage_excessive_reservation_threshold": 0.50,
        "ghs_storage_daily_growth_warning_bytes": 2_500,
        "ghs_storage_temp_dir": tmp_path / "tmp",
    }
    defaults.update(overrides)
    return Settings(**defaults)


async def _make_stack(
    tmp_path: Path, **setting_overrides: Any
) -> tuple[
    Settings,
    LocalObjectStore,
    SqlAlchemyStorageLedgerRepository,
    StorageZoneManager,
    StorageQuotaManager,
    ContentDeduplicationService,
    StorageLifecycleManager,
    StorageMonitoringService,
    AsyncEngine,
]:
    settings = _make_settings(tmp_path, **setting_overrides)
    store = LocalObjectStore(settings.local_storage_dir)
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(GhsBase.metadata.create_all)
    ledger = SqlAlchemyStorageLedgerRepository(build_session_factory(engine))
    zones = StorageZoneManager(settings)
    quota = StorageQuotaManager(ledger, store, settings)
    dedup = ContentDeduplicationService(store, ledger, zones, settings)
    lifecycle = StorageLifecycleManager(store, ledger, zones, settings)
    monitoring = StorageMonitoringService(ledger, quota, zones, settings)
    return settings, store, ledger, zones, quota, dedup, lifecycle, monitoring, engine


def test_quota_estimation_and_warnings(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    store = LocalObjectStore(settings.local_storage_dir)

    class _NoopLedger:
        pass

    quota = StorageQuotaManager(_NoopLedger(), store, settings)  # type: ignore[arg-type]
    grid = GridSpec(
        crs="EPSG:4326",
        bounds=SpatialBounds(min_x=0.0, min_y=0.0, max_x=10.0, max_y=10.0),
        resolution_x=0.1,
        resolution_y=0.1,
        resolution_unit="degree",
    )
    est_f64 = quota.estimate_grid_output_bytes(grid, variable_count=2, dtype="float64")
    est_f32 = quota.estimate_grid_output_bytes(grid, variable_count=2, dtype="float32")
    assert est_f64 > est_f32 > 65_536

    payload_file = tmp_path / "sample.bin"
    payload_file.write_bytes(b"x" * 777)
    assert quota.estimate_upload_bytes(source_path=payload_file) == 777
    assert quota.estimate_upload_bytes(payload_bytes=555) == 555

    disabled = StorageQuotaManager(
        _NoopLedger(),  # type: ignore[arg-type]
        store,
        _make_settings(tmp_path, ghs_storage_estimation_enabled=False),
    )
    assert disabled.estimate_grid_output_bytes(grid) == 1
    assert disabled.estimate_upload_bytes() == 1


def test_evaluate_warnings_covers_all_signals(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path)
    store = LocalObjectStore(settings.local_storage_dir)

    class _NoopLedger:
        pass

    quota = StorageQuotaManager(_NoopLedger(), store, settings)  # type: ignore[arg-type]
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    metrics_hard = StorageUsageMetricsSnapshot(
        total_stored_bytes=4_500,
        object_count=3,
        reserved_bytes=6_000,
        zones={
            "raw": ZoneUsageSummary(
                zone="raw",
                object_count=1,
                stored_bytes=2_000,
                reserved_bytes=0,
                original_bytes=2_000,
                compression_saved_bytes=0,
                dedup_saved_bytes=0,
            ),
            "intermediate": ZoneUsageSummary(
                zone="intermediate",
                object_count=1,
                stored_bytes=1_000,
                reserved_bytes=0,
                original_bytes=1_000,
                compression_saved_bytes=0,
                dedup_saved_bytes=0,
            ),
            "derived": ZoneUsageSummary(
                zone="derived",
                object_count=1,
                stored_bytes=1_500,
                reserved_bytes=0,
                original_bytes=1_900,
                compression_saved_bytes=400,
                dedup_saved_bytes=200,
            ),
        },
        daily_growth_bytes=3_000,
        compression_savings_bytes=400,
        deduplication_savings_bytes=200,
        cleanup_deleted_objects=0,
        cleanup_reclaimed_bytes=0,
        failed_uploads_count=0,
        orphaned_objects_count=2,
        missing_referenced_objects_count=1,
        last_reconciliation_diff_bytes=-256,
        last_reconciliation_at=now,
    )
    warnings = quota.evaluate_warnings(metrics_hard, job_reserved_bytes=3_500)
    codes = {w.code for w in warnings}
    assert {
        "BUDGET_HARD_LIMIT",
        "EXCESSIVE_RESERVATIONS",
        "JOB_ALLOCATION_HIGH",
        "UNEXPECTED_GROWTH",
        "RECONCILIATION_DRIFT",
        "MISSING_REFERENCED_OBJECT",
        "ORPHANED_OBJECTS_DETECTED",
    }.issubset(codes)

    metrics_warn = StorageUsageMetricsSnapshot(
        total_stored_bytes=8_200,
        object_count=1,
        reserved_bytes=0,
        zones={},
        daily_growth_bytes=100,
        compression_savings_bytes=0,
        deduplication_savings_bytes=0,
        cleanup_deleted_objects=0,
        cleanup_reclaimed_bytes=0,
        failed_uploads_count=0,
        orphaned_objects_count=0,
        missing_referenced_objects_count=0,
        last_reconciliation_diff_bytes=0,
        last_reconciliation_at=now,
    )
    warn_codes = {w.code for w in quota.evaluate_warnings(metrics_warn)}
    assert "BUDGET_WARNING" in warn_codes
    assert "BUDGET_HARD_LIMIT" not in warn_codes


async def test_reservation_scope_commit_fail_and_concurrency(tmp_path: Path) -> None:
    _, _, ledger, _, quota, _, _, _, engine = await _make_stack(tmp_path)
    try:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        await ledger.ensure_ledger_initialized(now)

        async with quota.reservation_scope(
            estimated_bytes=1_200,
            zone="derived",
            operation="write_cog",
            job_id="job-ok",
            now=now,
        ) as handle:
            handle.actual_bytes = 650

        res_ok = await ledger.get_reservation(handle.reservation.reservation_id)
        assert res_ok is not None
        assert res_ok.status == "committed"
        assert res_ok.actual_bytes == 650

        with pytest.raises(RuntimeError, match="boom"):
            async with quota.reservation_scope(
                estimated_bytes=1_500,
                zone="intermediate",
                operation="tmp_warp",
                job_id="job-fail",
                now=now,
            ) as fail_handle:
                raise RuntimeError("boom")

        res_fail = await ledger.get_reservation(fail_handle.reservation.reservation_id)
        assert res_fail is not None
        assert res_fail.status == "failed"

        async def _try_reserve(idx: int) -> bool:
            try:
                await quota.reserve_for_operation(
                    estimated_bytes=3_000,
                    zone="derived",
                    operation=f"op-{idx}",
                    job_id=f"j-{idx}",
                    now=now,
                )
            except StorageBudgetExceededError:
                return False
            return True

        outcomes = await asyncio.gather(*(_try_reserve(i) for i in range(5)))
        assert sum(1 for ok in outcomes if ok) == 3

        expired = await quota.reconcile_expired_reservations(now=now + timedelta(seconds=120))
        assert len(expired) == 3
        metrics = await ledger.get_usage_metrics(now + timedelta(seconds=120))
        assert metrics.reserved_bytes == 0
    finally:
        await engine.dispose()


async def test_deduplication_shares_binary_but_preserves_provenance_and_heals_missing(
    tmp_path: Path,
) -> None:
    _, store, _, zones, _, dedup, _, monitoring, engine = await _make_stack(tmp_path)
    try:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        src_file = tmp_path / "input.nc"
        src_file.write_bytes(b"scientific-payload-bytes" * 40)
        digest, size_bytes = compute_file_sha256(src_file)

        bad_key = zones.raw_key("modis", "MOD11A1", "ds-bad", "file1.nc")
        with pytest.raises(StorageIntegrityError, match="Checksum verification failed"):
            await dedup.store_or_deduplicate_file(
                source_path=src_file,
                zone="raw",
                object_key=bad_key,
                ref=AssetReferenceLink(
                    object_key=bad_key,
                    ref_kind="dataset",
                    ref_owner_id="ds-bad",
                    asset_id="a-bad",
                    provider="modis",
                    product="MOD11A1",
                    created_at=now,
                ),
                media_type="application/x-netcdf",
                data_format="netcdf",
                verify_sha256="0" * 64,
                now=now,
            )

        wrong_zone_key = zones.raw_key("modis", "MOD11A1", "ds-zone", "wrong_zone.nc")
        with pytest.raises(StorageIntegrityError, match="belongs to zone"):
            await dedup.store_or_deduplicate_file(
                source_path=src_file,
                zone="derived",
                object_key=wrong_zone_key,
                ref=AssetReferenceLink(
                    object_key=wrong_zone_key,
                    ref_kind="dataset",
                    ref_owner_id="ds-zone",
                    asset_id="a-zone",
                    provider="modis",
                    product="MOD11A1",
                    created_at=now,
                ),
                media_type="application/x-netcdf",
                data_format="netcdf",
                now=now,
            )

        key_1 = zones.raw_key("modis", "MOD11A1", "ds-1", "ds1.nc")
        res_1 = await dedup.store_or_deduplicate_file(
            source_path=src_file,
            zone="raw",
            object_key=key_1,
            ref=AssetReferenceLink(
                object_key=key_1,
                ref_kind="dataset",
                ref_owner_id="ds-1",
                asset_id="asset-ds-1",
                provider="nasa_cmr",
                product="MOD11A1",
                created_at=now,
                metadata={"tile": "h12v04"},
            ),
            media_type="application/x-netcdf",
            data_format="netcdf",
            verify_sha256=digest,
            now=now,
        )
        assert not res_1.deduplicated
        assert res_1.saved_bytes == 0
        assert res_1.record.ref_count == 1

        key_2 = zones.raw_key("modis", "MOD11A1", "ds-2", "ds2.nc")
        res_2 = await dedup.store_or_deduplicate_file(
            source_path=src_file,
            zone="raw",
            object_key=key_2,
            ref=AssetReferenceLink(
                object_key=key_2,
                ref_kind="dataset",
                ref_owner_id="ds-2",
                asset_id="asset-ds-2",
                provider="nasa_cmr",
                product="MYD11A1",
                created_at=now,
                metadata={"tile": "h12v04", "sensor": "aqua"},
            ),
            media_type="application/x-netcdf",
            data_format="netcdf",
            now=now,
        )
        assert res_2.deduplicated
        assert res_2.saved_bytes == size_bytes
        assert res_2.record.object_key == key_1
        assert res_2.record.ref_count == 2
        assert not await store.exists(key_2)

        async with build_session_factory(engine)() as session:
            ref_rows = (
                (
                    await session.execute(
                        select(GhsStorageAssetRefModel).where(
                            GhsStorageAssetRefModel.object_key == key_1
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {r.ref_owner_id for r in ref_rows} == {"ds-1", "ds-2"}
        assert {r.product for r in ref_rows} == {"MOD11A1", "MYD11A1"}

        await store.delete_object(key_1)
        key_3 = zones.raw_key("modis", "MOD11A1", "ds-3", "ds3.nc")
        res_3 = await dedup.store_or_deduplicate_file(
            source_path=src_file,
            zone="raw",
            object_key=key_3,
            ref=AssetReferenceLink(
                object_key=key_3,
                ref_kind="dataset",
                ref_owner_id="ds-3",
                asset_id="asset-ds-3",
                provider="nasa_cmr",
                product="MOD11A1",
                created_at=now,
            ),
            media_type="application/x-netcdf",
            data_format="netcdf",
            now=now,
        )
        assert not res_3.deduplicated
        assert await store.exists(key_3)

        usage = await monitoring.get_usage_summary(now=now)
        assert usage.deduplication_savings_bytes == size_bytes
        assert usage.object_count == 2
    finally:
        await engine.dispose()


async def test_lifecycle_safety_mark_and_sweep_grace_dry_run_and_reconciliation(
    tmp_path: Path,
) -> None:
    settings, store, ledger, zones, quota, dedup, lifecycle, monitoring, engine = await _make_stack(
        tmp_path,
        ghs_storage_intermediate_retention_seconds=300,
        ghs_storage_orphan_grace_seconds=30,
        ghs_admin_token=SecretStr("super-secret-admin-token"),
        earthdata_token=SecretStr("super-secret-earthdata-token"),
    )
    try:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

        raw_file = tmp_path / "raw.bin"
        raw_file.write_bytes(b"R" * 400)
        raw_key = zones.raw_key("gpm", "3IMERGHH", "raw-ds-1", "imerg.nc")
        await dedup.store_or_deduplicate_file(
            source_path=raw_file,
            zone="raw",
            object_key=raw_key,
            ref=AssetReferenceLink(
                object_key=raw_key,
                ref_kind="dataset",
                ref_owner_id="raw-ds-1",
                asset_id="raw-a1",
                provider="gpm",
                product="3IMERGHH",
                created_at=now,
            ),
            media_type="application/x-netcdf",
            data_format="netcdf",
            now=now,
        )
        await lifecycle.release_owner_references("dataset", "raw-ds-1", now=now)
        with pytest.raises(StorageImmutabilityError):
            zones.assert_deletable(raw_key, reason="job_completed")

        derived_file = tmp_path / "derived.tif"
        derived_file.write_bytes(b"D" * 500)
        derived_key = zones.derived_key("res-1", "ndvi.tif")
        await dedup.store_or_deduplicate_file(
            source_path=derived_file,
            zone="derived",
            object_key=derived_key,
            ref=AssetReferenceLink(
                object_key=derived_key,
                ref_kind="result",
                ref_owner_id="sci-res-1",
                asset_id="der-a1",
                provider="internal",
                product="NDVI",
                created_at=now,
            ),
            media_type="image/tiff",
            data_format="geotiff",
            original_size_bytes=900,
            compression_codec="ZSTD",
            now=now,
        )

        inter_expired_file = tmp_path / "inter1.tif"
        inter_expired_file.write_bytes(b"I" * 300)
        inter_expired_key = zones.intermediate_key("job-exp", "part.tif")
        await dedup.store_or_deduplicate_file(
            source_path=inter_expired_file,
            zone="intermediate",
            object_key=inter_expired_key,
            ref=AssetReferenceLink(
                object_key=inter_expired_key,
                ref_kind="job",
                ref_owner_id="job-exp",
                asset_id="int-a1",
                provider="internal",
                product="WARP",
                created_at=now,
            ),
            media_type="image/tiff",
            data_format="geotiff",
            now=now,
        )

        inter_shared_file = tmp_path / "inter_shared.tif"
        inter_shared_file.write_bytes(b"S" * 350)
        inter_shared_key = zones.intermediate_key("job-s1", "shared.tif")
        await dedup.store_or_deduplicate_file(
            source_path=inter_shared_file,
            zone="intermediate",
            object_key=inter_shared_key,
            ref=AssetReferenceLink(
                object_key=inter_shared_key,
                ref_kind="job",
                ref_owner_id="job-s1",
                asset_id="int-s1",
                provider="internal",
                product="WARP",
                created_at=now,
            ),
            media_type="image/tiff",
            data_format="geotiff",
            now=now,
        )
        shared_obj = await ledger.get_object(inter_shared_key)
        assert shared_obj is not None
        await ledger.register_object_and_ref(
            shared_obj,
            AssetReferenceLink(
                object_key=inter_shared_key,
                ref_kind="job",
                ref_owner_id="job-s2",
                asset_id="int-s2",
                provider="internal",
                product="WARP",
                created_at=now,
            ),
            now,
        )

        deleted_s1 = await lifecycle.on_job_completed("job-s1", success=False, now=now)
        assert deleted_s1 == ()
        assert await store.exists(inter_shared_key)

        deleted_s2 = await lifecycle.on_job_completed("job-s2", success=False, now=now)
        assert deleted_s2 == (inter_shared_key,)
        assert not await store.exists(inter_shared_key)

        untracked_key = "derived/unknown_manual/mystery.tif"
        await store.put_bytes(untracked_key, b"M" * 200, "image/tiff")
        abandoned_tmp = settings.local_storage_dir / ".ghs-tmp-abandoned.part"
        abandoned_tmp.write_bytes(b"tmp")
        stale_ts = time.time() - 3600
        os.utime(abandoned_tmp, (stale_ts, stale_ts))

        orphan_active_file = tmp_path / "orphan_unexpired.tif"
        orphan_active_file.write_bytes(b"O" * 250)
        later = now + timedelta(seconds=350)
        orphan_key = zones.intermediate_key("job-unexp", "orphan.tif")
        await dedup.store_or_deduplicate_file(
            source_path=orphan_active_file,
            zone="intermediate",
            object_key=orphan_key,
            ref=AssetReferenceLink(
                object_key=orphan_key,
                ref_kind="job",
                ref_owner_id="job-unexp",
                asset_id="int-o1",
                provider="internal",
                product="WARP",
                created_at=later,
            ),
            media_type="image/tiff",
            data_format="geotiff",
            now=later,
        )
        await lifecycle.release_owner_references("job", "job-unexp", now=later)
        await lifecycle.release_owner_references("job", "job-exp", now=now)

        inter_busy_file = tmp_path / "inter_busy.tif"
        inter_busy_file.write_bytes(b"B" * 150)
        inter_busy_key = zones.intermediate_key("job-busy", "busy.tif")
        await dedup.store_or_deduplicate_file(
            source_path=inter_busy_file,
            zone="intermediate",
            object_key=inter_busy_key,
            ref=AssetReferenceLink(
                object_key=inter_busy_key,
                ref_kind="job",
                ref_owner_id="job-busy",
                asset_id="int-busy",
                provider="internal",
                product="WARP",
                created_at=now,
            ),
            media_type="image/tiff",
            data_format="geotiff",
            now=now,
        )

        dry = await lifecycle.run_maintenance_cycle(dry_run=True, grace_seconds=30, now=later)
        assert dry.dry_run
        assert inter_expired_key in dry.expired_intermediate_deleted
        assert inter_busy_key not in dry.expired_intermediate_deleted
        assert inter_expired_key not in dry.orphans_marked
        assert orphan_key in dry.orphans_marked
        assert dry.orphans_swept == ()
        assert raw_key in dry.skipped_protected
        assert untracked_key in dry.skipped_protected
        assert await store.exists(inter_expired_key)
        assert await store.exists(inter_busy_key)
        assert abandoned_tmp.exists()

        sweep_1 = await lifecycle.run_maintenance_cycle(dry_run=False, grace_seconds=30, now=later)
        assert inter_expired_key in sweep_1.expired_intermediate_deleted
        assert inter_busy_key not in sweep_1.expired_intermediate_deleted
        assert orphan_key in sweep_1.orphans_marked
        assert sweep_1.orphans_swept == ()
        assert sweep_1.abandoned_temp_files_removed == 1
        assert not await store.exists(inter_expired_key)
        assert await store.exists(inter_busy_key)
        assert await store.exists(orphan_key)
        assert await store.exists(raw_key)
        assert await store.exists(derived_key)
        assert await store.exists(untracked_key)

        after_grace = later + timedelta(seconds=35)
        sweep_2 = await lifecycle.run_maintenance_cycle(
            dry_run=False, grace_seconds=30, now=after_grace
        )
        assert orphan_key in sweep_2.orphans_swept
        assert not await store.exists(orphan_key)
        assert await store.exists(inter_busy_key)
        assert await store.exists(raw_key)
        assert await store.exists(derived_key)
        assert await store.exists(untracked_key)

        reconcile = await quota.reconcile_ledger_with_store(now=after_grace)
        assert reconcile.untracked_keys == (untracked_key,)
        assert reconcile.bytes_difference == 200
        assert any(w.code == "RECONCILIATION_DRIFT" for w in reconcile.warnings)

        await lifecycle.on_job_completed("job-busy", success=True, now=after_grace)
        assert not await store.exists(inter_busy_key)

        usage = await monitoring.get_usage_summary(now=after_grace)
        assert usage.compression_savings_bytes == 400
        assert usage.reconciliation_diff_bytes == 200
        policy_json = json.dumps(monitoring.get_policy_summary())
        assert "super-secret-admin-token" not in policy_json
        assert "super-secret-earthdata-token" not in policy_json
    finally:
        await engine.dispose()
