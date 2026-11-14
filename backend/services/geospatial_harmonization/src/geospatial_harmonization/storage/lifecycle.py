"""Storage lifecycle manager enforcing retention, mark-and-sweep, and reference safety."""

from datetime import UTC, datetime, timedelta

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.models.storage import (
    CleanupReport,
    OrphanReport,
    ReferenceKind,
    StorageObjectRecord,
)
from geospatial_harmonization.domain.models.temporal import require_tz_aware
from geospatial_harmonization.domain.ports import StorageLedgerRepository, StoragePort
from geospatial_harmonization.storage.zones import StorageZoneManager


class StorageLifecycleManager:
    """Manages TTL expiration, failed artifact cleanup, and reference-safe mark-and-sweep."""

    def __init__(
        self,
        storage: StoragePort,
        ledger: StorageLedgerRepository,
        zones: StorageZoneManager,
        settings: Settings | None = None,
    ) -> None:
        self._storage = storage
        self._ledger = ledger
        self._zones = zones
        self._settings = settings or get_settings()

    async def inspect_orphans(self, *, now: datetime | None = None) -> OrphanReport:
        """Identify untracked physical keys, unreferenced ledger objects, and missing assets."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        require_tz_aware(ref_now, "now")
        physical_items = await self._storage.list_objects()
        ledger_items = await self._ledger.list_objects()

        physical_keys = {item.key for item in physical_items}
        ledger_keys = {item.object_key for item in ledger_items}

        untracked = tuple(sorted(physical_keys - ledger_keys))
        missing = tuple(sorted(ledger_keys - physical_keys))
        unreferenced = tuple(
            sorted(
                item.object_key
                for item in ledger_items
                if item.ref_count == 0 and item.zone != "raw"
            )
        )
        return OrphanReport(
            untracked_in_store=untracked,
            unreferenced_in_ledger=unreferenced,
            missing_from_store=missing,
            checked_at=ref_now,
        )

    async def _delete_unreferenced_object(
        self,
        obj: StorageObjectRecord,
        *,
        reason: str,
        now_utc: datetime,
        dry_run: bool,
    ) -> bool:
        if await self._ledger.has_active_references(obj.object_key):
            return False
        self._zones.assert_deletable(obj.object_key, reason=reason)
        if dry_run:
            return True
        await self._storage.delete_object(obj.object_key)
        return await self._ledger.delete_object_record(obj.object_key, now_utc)

    async def on_job_completed(
        self,
        job_id: str,
        *,
        success: bool,
        cleanup_intermediate: bool = True,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Detach job refs and safely delete unreferenced intermediate/failed-job artifacts."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        unlinked = await self._ledger.remove_asset_references_for_owner("job", job_id, ref_now)
        if not unlinked or not cleanup_intermediate:
            return ()

        reason = "job_completed" if success else "job_failed"
        allowed_zones: tuple[str, ...] = (
            ("intermediate",) if success else ("intermediate", "derived")
        )
        deleted: list[str] = []
        reclaimed = 0
        for key in unlinked:
            obj = await self._ledger.get_object(key)
            if obj is None or obj.zone not in allowed_zones:
                continue
            if await self._ledger.has_active_references(key):
                continue
            self._zones.assert_deletable(key, reason=reason)
            await self._storage.delete_object(key)
            if await self._ledger.delete_object_record(key, ref_now):
                deleted.append(key)
                reclaimed += obj.size_bytes
        if not success and deleted:
            await self._ledger.record_audit_event(
                "failed_job_cleanup",
                None,
                None,
                -reclaimed,
                0,
                {"job_id": job_id, "deleted_count": len(deleted)},
                ref_now,
            )
        return tuple(sorted(deleted))

    async def release_owner_references(
        self,
        ref_kind: ReferenceKind,
        ref_owner_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Remove dataset/result ownership links without deleting shared referenced objects."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        return await self._ledger.remove_asset_references_for_owner(ref_kind, ref_owner_id, ref_now)

    async def run_maintenance_cycle(
        self,
        *,
        dry_run: bool = False,
        grace_seconds: int | None = None,
        include_expired_derived: bool = False,
        now: datetime | None = None,
    ) -> CleanupReport:
        """Execute expiration, temp/multipart cleanup, and grace-protected mark-and-sweep."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        require_tz_aware(ref_now, "now")
        grace = (
            grace_seconds
            if grace_seconds is not None
            else self._settings.ghs_storage_orphan_grace_seconds
        )
        if grace < 0:
            raise ValueError("grace_seconds must be >= 0")

        await self._ledger.reconcile_expired_reservations(ref_now)

        temp_removed = 0
        multipart_aborted = 0
        if not dry_run:
            temp_removed = await self._storage.cleanup_abandoned_temp_files(
                older_than_seconds=self._settings.ghs_storage_abandoned_temp_max_age_seconds
            )
            multipart_aborted = await self._storage.abort_incomplete_multipart_uploads(
                older_than_seconds=self._settings.ghs_storage_abandoned_temp_max_age_seconds
            )

        expired_deleted: list[str] = []
        skipped_protected: list[str] = []
        reclaimed_bytes = 0

        for candidate in await self._ledger.list_expired_intermediate_objects(ref_now):
            if await self._ledger.has_active_references(candidate.object_key):
                skipped_protected.append(candidate.object_key)
                continue
            if await self._delete_unreferenced_object(
                candidate, reason="expired_ttl", now_utc=ref_now, dry_run=dry_run
            ):
                expired_deleted.append(candidate.object_key)
                reclaimed_bytes += candidate.size_bytes

        orphan_report = await self.inspect_orphans(now=ref_now)
        expired_deleted_set = set(expired_deleted)
        orphans_marked: list[str] = []
        orphans_swept: list[str] = []

        all_live = await self._ledger.list_objects()
        for obj in all_live:
            if obj.object_key in expired_deleted_set:
                continue
            if obj.ref_count > 0 or await self._ledger.has_active_references(obj.object_key):
                if obj.status == "marked_orphan":
                    skipped_protected.append(obj.object_key)
                continue

            if obj.zone == "raw":
                skipped_protected.append(obj.object_key)
                continue

            if obj.zone == "derived" and (
                not include_expired_derived or obj.expires_at is None or obj.expires_at > ref_now
            ):
                skipped_protected.append(obj.object_key)
                continue

            if obj.status == "active":
                if not dry_run:
                    await self._ledger.mark_object_orphan(obj.object_key, ref_now)
                orphans_marked.append(obj.object_key)

        sweep_cutoff = ref_now - timedelta(seconds=grace)
        for sweep_obj in await self._ledger.list_orphan_sweep_candidates(sweep_cutoff):
            if sweep_obj.zone == "raw":
                skipped_protected.append(sweep_obj.object_key)
                continue
            if await self._ledger.has_active_references(sweep_obj.object_key):
                skipped_protected.append(sweep_obj.object_key)
                continue
            if await self._delete_unreferenced_object(
                sweep_obj, reason="orphan_sweep", now_utc=ref_now, dry_run=dry_run
            ):
                orphans_swept.append(sweep_obj.object_key)
                reclaimed_bytes += sweep_obj.size_bytes

        # Untracked physical keys lack deterministic ownership records and are never auto-deleted.
        skipped_protected.extend(orphan_report.untracked_in_store)

        report = CleanupReport(
            dry_run=dry_run,
            expired_intermediate_deleted=tuple(sorted(expired_deleted)),
            failed_job_artifacts_deleted=(),
            orphans_marked=tuple(sorted(orphans_marked)),
            orphans_swept=tuple(sorted(orphans_swept)),
            missing_detected=orphan_report.missing_from_store,
            abandoned_temp_files_removed=temp_removed,
            abandoned_multipart_aborted=multipart_aborted,
            reclaimed_bytes=reclaimed_bytes,
            skipped_protected=tuple(sorted(set(skipped_protected))),
            executed_at=ref_now,
        )
        await self._ledger.record_audit_event(
            event_type="cleanup_dry_run" if dry_run else "cleanup_sweep",
            zone=None,
            object_key=None,
            bytes_delta=0 if dry_run else -reclaimed_bytes,
            saved_bytes=reclaimed_bytes,
            details={
                "dry_run": dry_run,
                "expired_intermediate_deleted": len(report.expired_intermediate_deleted),
                "orphans_marked": len(report.orphans_marked),
                "orphans_swept": len(report.orphans_swept),
                "abandoned_temp_files_removed": temp_removed,
                "abandoned_multipart_aborted": multipart_aborted,
                "missing_detected": len(report.missing_detected),
            },
            now=ref_now,
        )
        return report
