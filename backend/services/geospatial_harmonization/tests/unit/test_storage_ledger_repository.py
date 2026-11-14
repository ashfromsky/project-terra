"""Tests for SqlAlchemyStorageLedgerRepository concurrency, ref counting, and metrics."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.domain.exceptions import (
    ObjectTooLargeError,
    StorageBudgetExceededError,
    StorageImmutabilityError,
    StorageReservationError,
)
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    StorageObjectRecord,
    StorageReservation,
)
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository


async def _make_repo(tmp_path: Path) -> tuple[SqlAlchemyStorageLedgerRepository, AsyncEngine]:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(GhsBase.metadata.create_all)
    return SqlAlchemyStorageLedgerRepository(build_session_factory(engine)), engine


async def test_concurrent_reservations_cannot_exceed_budget(tmp_path: Path) -> None:
    repo, engine = await _make_repo(tmp_path)
    try:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        await repo.ensure_ledger_initialized(now)

        async def _attempt(idx: int) -> str:
            res = StorageReservation(
                reservation_id=uuid4(),
                job_id=f"job-{idx}",
                operation="derived_write",
                zone="derived",
                reserved_bytes=150,
                status="active",
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            try:
                await repo.reserve_capacity(
                    res,
                    budget_bytes=1000,
                    hard_limit_threshold=1.0,
                    max_object_bytes=500,
                    max_job_output_bytes=500,
                    now=now,
                )
                return "ok"
            except StorageBudgetExceededError:
                return "rejected"

        outcomes = await asyncio.gather(*(_attempt(i) for i in range(20)))
        assert outcomes.count("ok") == 6
        assert outcomes.count("rejected") == 14

        metrics = await repo.get_usage_metrics(now)
        assert metrics.reserved_bytes == 900
        assert metrics.zones["derived"].reserved_bytes == 900
    finally:
        await engine.dispose()


async def test_reservation_limits_commit_release_and_expiration(tmp_path: Path) -> None:
    repo, engine = await _make_repo(tmp_path)
    try:
        t0 = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
        with pytest.raises(ObjectTooLargeError) as exc_obj:
            await repo.reserve_capacity(
                StorageReservation(
                    reservation_id=uuid4(),
                    job_id="j1",
                    operation="raw_ingest",
                    zone="raw",
                    reserved_bytes=600,
                    status="active",
                    created_at=t0,
                    expires_at=t0 + timedelta(minutes=10),
                ),
                budget_bytes=5000,
                hard_limit_threshold=1.0,
                max_object_bytes=500,
                max_job_output_bytes=400,
                now=t0,
            )
        assert exc_obj.value.scope == "object"

        res_job_1 = StorageReservation(
            reservation_id=uuid4(),
            job_id="j-multi",
            operation="derived_write",
            zone="derived",
            reserved_bytes=300,
            status="active",
            created_at=t0,
            expires_at=t0 + timedelta(minutes=5),
        )
        await repo.reserve_capacity(
            res_job_1,
            budget_bytes=5000,
            hard_limit_threshold=1.0,
            max_object_bytes=500,
            max_job_output_bytes=400,
            now=t0,
        )
        with pytest.raises(ObjectTooLargeError) as exc_job:
            await repo.reserve_capacity(
                StorageReservation(
                    reservation_id=uuid4(),
                    job_id="j-multi",
                    operation="derived_write",
                    zone="derived",
                    reserved_bytes=150,
                    status="active",
                    created_at=t0,
                    expires_at=t0 + timedelta(minutes=5),
                ),
                budget_bytes=5000,
                hard_limit_threshold=1.0,
                max_object_bytes=500,
                max_job_output_bytes=400,
                now=t0,
            )
        assert exc_job.value.scope == "job_output"

        committed = await repo.commit_reservation(
            res_job_1.reservation_id, actual_bytes=180, now=t0 + timedelta(seconds=30)
        )
        assert committed.status == "committed"
        assert committed.actual_bytes == 180
        with pytest.raises(StorageReservationError, match="already committed"):
            await repo.release_reservation(
                res_job_1.reservation_id, "released", t0 + timedelta(seconds=40)
            )

        res_exp = StorageReservation(
            reservation_id=uuid4(),
            job_id="j-exp",
            operation="intermediate_write",
            zone="intermediate",
            reserved_bytes=700,
            status="active",
            created_at=t0,
            expires_at=t0 + timedelta(minutes=5),
        )
        await repo.reserve_capacity(
            res_exp,
            budget_bytes=1000,
            hard_limit_threshold=1.0,
            max_object_bytes=900,
            max_job_output_bytes=900,
            now=t0,
        )

        later = t0 + timedelta(minutes=6)
        fresh = StorageReservation(
            reservation_id=uuid4(),
            job_id="j-fresh",
            operation="derived_write",
            zone="derived",
            reserved_bytes=500,
            status="active",
            created_at=later,
            expires_at=later + timedelta(minutes=10),
        )
        await repo.reserve_capacity(
            fresh,
            budget_bytes=1000,
            hard_limit_threshold=1.0,
            max_object_bytes=900,
            max_job_output_bytes=900,
            now=later,
        )
        expired_row = await repo.get_reservation(res_exp.reservation_id)
        assert expired_row is not None and expired_row.status == "expired"

        failed = await repo.release_reservation(
            fresh.reservation_id, "failed", later + timedelta(seconds=5), reason="network_error"
        )
        assert failed.status == "failed"
        assert failed.notes == "network_error"

        metrics = await repo.get_usage_metrics(later + timedelta(seconds=10))
        assert metrics.reserved_bytes == 0
        assert metrics.failed_uploads_count == 1
    finally:
        await engine.dispose()


async def test_object_registration_ref_safety_lifecycle_and_metrics(tmp_path: Path) -> None:
    repo, engine = await _make_repo(tmp_path)
    try:
        t0 = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
        digest = "a" * 64
        raw_obj = StorageObjectRecord(
            object_key="raw/modis/MOD13Q1/aaaa/tile.hdf",
            zone="raw",
            content_sha256=digest,
            size_bytes=800,
            original_size_bytes=1000,
            media_type="application/x-hdf",
            data_format="hdf4",
            compression_codec="ZSTD",
            created_at=t0,
            updated_at=t0,
        )
        ref1 = AssetReferenceLink(
            object_key=raw_obj.object_key,
            ref_kind="dataset",
            ref_owner_id="ds-1",
            asset_id="tile.hdf",
            provider="modis",
            product="MOD13Q1",
            created_at=t0,
        )
        rec1, created = await repo.register_object_and_ref(raw_obj, ref1, t0)
        assert created is True
        assert rec1.ref_count == 1

        ref2 = AssetReferenceLink(
            object_key=raw_obj.object_key,
            ref_kind="result",
            ref_owner_id="res-1",
            asset_id="tile.hdf",
            provider="modis",
            product="MOD13Q1",
            created_at=t0,
        )
        assert await repo.add_asset_reference(ref2, t0) is True
        assert await repo.add_asset_reference(ref2, t0) is False

        found = await repo.find_active_by_checksum(digest, zone="raw")
        assert found is not None and found.ref_count == 2

        with pytest.raises(StorageImmutabilityError, match="active refs"):
            await repo.delete_object_record(raw_obj.object_key, t0)
        with pytest.raises(StorageImmutabilityError, match="referenced"):
            await repo.mark_object_orphan(raw_obj.object_key, t0)

        inter_obj = StorageObjectRecord(
            object_key="intermediate/job-9/work/temp.tif",
            zone="intermediate",
            content_sha256="b" * 64,
            size_bytes=300,
            media_type="image/tiff",
            data_format="geotiff",
            created_at=t0,
            updated_at=t0,
            expires_at=t0 + timedelta(minutes=15),
        )
        inter_ref = AssetReferenceLink(
            object_key=inter_obj.object_key,
            ref_kind="job",
            ref_owner_id="job-9",
            asset_id="temp.tif",
            provider="generic",
            product="custom",
            created_at=t0,
        )
        await repo.register_object_and_ref(inter_obj, inter_ref, t0, dedup_saved_bytes=200)

        expired_before_detach = await repo.list_expired_intermediate_objects(
            t0 + timedelta(minutes=20)
        )
        assert expired_before_detach == ()

        removed = await repo.remove_asset_references_for_owner(
            "job", "job-9", t0 + timedelta(minutes=16)
        )
        assert removed == (inter_obj.object_key,)

        expired_after_detach = await repo.list_expired_intermediate_objects(
            t0 + timedelta(minutes=20)
        )
        assert [obj.object_key for obj in expired_after_detach] == [inter_obj.object_key]

        marked = await repo.mark_object_orphan(inter_obj.object_key, t0 + timedelta(minutes=20))
        assert marked is not None and marked.status == "marked_orphan"
        assert repo.list_orphan_sweep_candidates is not None
        assert await repo.list_orphan_sweep_candidates(t0 + timedelta(minutes=25)) == (marked,)

        assert (
            await repo.delete_object_record(inter_obj.object_key, t0 + timedelta(minutes=25))
            is True
        )

        await repo.record_reconciliation_snapshot(
            diff_bytes=50,
            orphaned_objects_count=1,
            missing_referenced_objects_count=0,
            checked_at=t0 + timedelta(minutes=30),
        )

        metrics = await repo.get_usage_metrics(t0 + timedelta(minutes=30))
        assert metrics.total_stored_bytes == 800
        assert metrics.object_count == 1
        assert metrics.compression_savings_bytes == 200
        assert metrics.deduplication_savings_bytes == 200
        assert metrics.cleanup_deleted_objects == 1
        assert metrics.cleanup_reclaimed_bytes == 300
        assert metrics.last_reconciliation_diff_bytes == 50
        assert metrics.zones["raw"].stored_bytes == 800
        assert metrics.zones["intermediate"].stored_bytes == 0
    finally:
        await engine.dispose()
