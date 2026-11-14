"""Storage quota guard, pre-write reservations, warnings, and ledger reconciliation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.models.storage import (
    ReconciliationReport,
    StorageReservation,
    StorageUsageMetricsSnapshot,
    StorageWarning,
    StorageZone,
)
from geospatial_harmonization.domain.models.temporal import require_tz_aware
from geospatial_harmonization.domain.ports import StorageLedgerRepository, StoragePort

_DTYPE_BYTES: dict[str, int] = {
    "float64": 8,
    "float32": 4,
    "int64": 8,
    "uint64": 8,
    "int32": 4,
    "uint32": 4,
    "int16": 2,
    "uint16": 2,
    "int8": 1,
    "uint8": 1,
}
_HEADER_OVERHEAD_BYTES = 65_536


@dataclass(slots=True)
class ReservationHandle:
    """Mutable handle yielded by reservation_scope to record actual bytes created."""

    reservation: StorageReservation
    actual_bytes: int | None = None


class StorageQuotaManager:
    """Enforces provider-independent storage budgets, reservations, warnings, and sync."""

    def __init__(
        self,
        ledger: StorageLedgerRepository,
        storage: StoragePort,
        settings: Settings | None = None,
    ) -> None:
        self._ledger = ledger
        self._storage = storage
        self._settings = settings or get_settings()

    @property
    def budget_bytes(self) -> int:
        return self._settings.ghs_storage_budget_bytes

    @property
    def hard_limit_bytes(self) -> int:
        return int(
            self._settings.ghs_storage_budget_bytes
            * self._settings.ghs_storage_hard_limit_threshold
        )

    def estimate_grid_output_bytes(
        self,
        grid: GridSpec,
        *,
        variable_count: int = 1,
        dtype: str = "float64",
        expected_compression_ratio: float = 0.75,
    ) -> int:
        """Estimate serialized raster output footprint from target grid dimensions and dtype."""
        if not self._settings.ghs_storage_estimation_enabled:
            return 1
        resolved = grid.resolved()
        sample_bytes = _DTYPE_BYTES.get(dtype.lower(), 8)
        raw_pixels = (resolved.width or 1) * (resolved.height or 1) * max(1, variable_count)
        ratio = max(0.05, min(1.5, expected_compression_ratio))
        return max(1, int(raw_pixels * sample_bytes * ratio) + _HEADER_OVERHEAD_BYTES)

    def estimate_upload_bytes(
        self,
        *,
        source_path: Path | None = None,
        payload_bytes: int | None = None,
        fallback_bytes: int = 1_048_576,
    ) -> int:
        """Determine reservation estimate from an input file, explicit payload size, or fallback."""
        if source_path is not None:
            return max(1, source_path.stat().st_size)
        if payload_bytes is not None:
            return max(1, payload_bytes)
        if not self._settings.ghs_storage_estimation_enabled:
            return 1
        return max(1, fallback_bytes)

    async def reserve_for_operation(
        self,
        *,
        estimated_bytes: int,
        zone: StorageZone,
        operation: str,
        job_id: str | None = None,
        ttl_seconds: int | None = None,
        notes: str | None = None,
        now: datetime | None = None,
    ) -> StorageReservation:
        """Atomically verify remaining quota and record a capacity reservation."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        require_tz_aware(ref_now, "now")
        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else self._settings.ghs_storage_reservation_ttl_seconds
        )
        if ttl <= 0:
            raise ValueError("ttl_seconds must be > 0")
        reservation = StorageReservation(
            reservation_id=uuid4(),
            job_id=job_id,
            operation=operation,
            zone=zone,
            reserved_bytes=max(0, estimated_bytes),
            status="active",
            created_at=ref_now,
            expires_at=ref_now + timedelta(seconds=ttl),
            notes=notes,
        )
        return await self._ledger.reserve_capacity(
            reservation,
            budget_bytes=self._settings.ghs_storage_budget_bytes,
            hard_limit_threshold=self._settings.ghs_storage_hard_limit_threshold,
            max_object_bytes=self._settings.ghs_storage_max_object_bytes,
            max_job_output_bytes=self._settings.ghs_storage_max_job_output_bytes,
            now=ref_now,
        )

    async def commit_reservation(
        self,
        reservation_id: UUID,
        *,
        actual_bytes: int,
        now: datetime | None = None,
    ) -> StorageReservation:
        """Reconcile actual created bytes and release unused reserved capacity."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        return await self._ledger.commit_reservation(reservation_id, actual_bytes, ref_now)

    async def release_reservation(
        self,
        reservation_id: UUID,
        *,
        status: Literal["released", "failed"] = "released",
        reason: str | None = None,
        now: datetime | None = None,
    ) -> StorageReservation:
        """Release reserved bytes cleanly on cancellation or failure."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        return await self._ledger.release_reservation(
            reservation_id, status, ref_now, reason=reason
        )

    @asynccontextmanager
    async def reservation_scope(
        self,
        *,
        estimated_bytes: int,
        zone: StorageZone,
        operation: str,
        job_id: str | None = None,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> AsyncIterator[ReservationHandle]:
        """Context guard ensuring reservations are committed on success or released on error."""
        reservation = await self.reserve_for_operation(
            estimated_bytes=estimated_bytes,
            zone=zone,
            operation=operation,
            job_id=job_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )
        handle = ReservationHandle(reservation=reservation)
        try:
            yield handle
        except BaseException as exc:
            await self.release_reservation(
                reservation.reservation_id,
                status="failed",
                reason=f"{type(exc).__name__}: {exc}"[:500],
            )
            raise
        actual = handle.actual_bytes if handle.actual_bytes is not None else 0
        await self.commit_reservation(reservation.reservation_id, actual_bytes=actual)

    async def reconcile_expired_reservations(
        self, *, now: datetime | None = None
    ) -> tuple[StorageReservation, ...]:
        """Expire overdue active reservations so stalled jobs never lock quota permanently."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        return await self._ledger.reconcile_expired_reservations(ref_now)

    def evaluate_warnings(
        self,
        metrics: StorageUsageMetricsSnapshot,
        *,
        job_reserved_bytes: int | None = None,
        reconciliation_diff_bytes: int | None = None,
    ) -> tuple[StorageWarning, ...]:
        """Build actionable warnings for threshold breaches, reservations, growth, and drift."""
        warnings: list[StorageWarning] = []
        budget = self._settings.ghs_storage_budget_bytes
        warn_bytes = int(budget * self._settings.ghs_storage_warning_threshold)
        hard_bytes = self.hard_limit_bytes
        projected = metrics.total_stored_bytes + metrics.reserved_bytes

        if projected >= hard_bytes:
            warnings.append(
                StorageWarning(
                    code="BUDGET_HARD_LIMIT",
                    severity="critical",
                    message=(
                        f"Allocated storage ({projected} bytes) has reached hard limit "
                        f"({hard_bytes} bytes of {budget} byte budget)."
                    ),
                    action=(
                        "Run lifecycle cleanup or prune unreferenced derived/intermediate assets."
                    ),
                    current_bytes=projected,
                    threshold_bytes=hard_bytes,
                )
            )
        elif projected >= warn_bytes:
            warnings.append(
                StorageWarning(
                    code="BUDGET_WARNING",
                    severity="warning",
                    message=(
                        f"Allocated storage ({projected} bytes) exceeds warning threshold "
                        f"({warn_bytes} bytes)."
                    ),
                    action="Inspect zone consumption and schedule intermediate/orphan cleanup.",
                    current_bytes=projected,
                    threshold_bytes=warn_bytes,
                )
            )

        excess_res_bytes = int(budget * self._settings.ghs_storage_excessive_reservation_threshold)
        if metrics.reserved_bytes > excess_res_bytes:
            warnings.append(
                StorageWarning(
                    code="EXCESSIVE_RESERVATIONS",
                    severity="warning",
                    message=(
                        f"Active storage reservations ({metrics.reserved_bytes} bytes) exceed "
                        f"threshold ({excess_res_bytes} bytes)."
                    ),
                    action="Reconcile expired reservations or inspect long-running worker jobs.",
                    current_bytes=metrics.reserved_bytes,
                    threshold_bytes=excess_res_bytes,
                )
            )

        if job_reserved_bytes is not None and job_reserved_bytes >= int(
            self._settings.ghs_storage_max_job_output_bytes * 0.80
        ):
            warnings.append(
                StorageWarning(
                    code="JOB_ALLOCATION_HIGH",
                    severity="warning",
                    message=(
                        f"Job reservation ({job_reserved_bytes} bytes) is above 80% of "
                        f"max job limit ({self._settings.ghs_storage_max_job_output_bytes} bytes)."
                    ),
                    action="Verify AOI clipping and lossless compression settings for this job.",
                    current_bytes=job_reserved_bytes,
                    threshold_bytes=self._settings.ghs_storage_max_job_output_bytes,
                )
            )

        growth_warn = self._settings.ghs_storage_daily_growth_warning_bytes
        if metrics.daily_growth_bytes >= growth_warn:
            warnings.append(
                StorageWarning(
                    code="UNEXPECTED_GROWTH",
                    severity="warning",
                    message=(
                        f"24h storage growth ({metrics.daily_growth_bytes} bytes) exceeded "
                        f"threshold ({growth_warn} bytes)."
                    ),
                    action=(
                        "Review recent ingestion/harmonization jobs for duplicate or global assets."
                    ),
                    current_bytes=metrics.daily_growth_bytes,
                    threshold_bytes=growth_warn,
                )
            )

        diff = (
            reconciliation_diff_bytes
            if reconciliation_diff_bytes is not None
            else metrics.last_reconciliation_diff_bytes
        )
        if diff is not None and diff != 0:
            warnings.append(
                StorageWarning(
                    code="RECONCILIATION_DRIFT",
                    severity="warning",
                    message=f"Object storage differs from ledger by {diff:+d} bytes.",
                    action="Run storage reconciliation and orphan inspection before cleanup.",
                    current_bytes=abs(diff),
                    threshold_bytes=0,
                    metadata={"bytes_difference": diff},
                )
            )

        if metrics.missing_referenced_objects_count > 0:
            warnings.append(
                StorageWarning(
                    code="MISSING_REFERENCED_OBJECT",
                    severity="critical",
                    message=(
                        f"Detected {metrics.missing_referenced_objects_count} ledger object(s) "
                        "missing from physical object storage."
                    ),
                    action=(
                        "Restore missing datasets or repair broken asset references immediately."
                    ),
                    metadata={"count": metrics.missing_referenced_objects_count},
                )
            )

        if metrics.orphaned_objects_count > 0:
            warnings.append(
                StorageWarning(
                    code="ORPHANED_OBJECTS_DETECTED",
                    severity="info",
                    message=(
                        f"Detected {metrics.orphaned_objects_count} orphaned or untracked "
                        "storage object(s)."
                    ),
                    action="Run dry-run lifecycle inspection and verify ownership before sweep.",
                    metadata={"count": metrics.orphaned_objects_count},
                )
            )

        return tuple(warnings)

    async def reconcile_ledger_with_store(
        self, *, prefix: str = "", now: datetime | None = None
    ) -> ReconciliationReport:
        """Compare physical object storage against the application ledger and record drift."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        expired = await self._ledger.reconcile_expired_reservations(ref_now)

        physical_items = await self._storage.list_objects(prefix)
        ledger_items = await self._ledger.list_objects()
        if prefix.strip("/"):
            norm_prefix = prefix.strip("/")
            ledger_items = tuple(
                item for item in ledger_items if item.object_key.startswith(norm_prefix)
            )

        physical_by_key = {item.key: item for item in physical_items}
        ledger_by_key = {item.object_key: item for item in ledger_items}

        untracked_keys = tuple(sorted(set(physical_by_key) - set(ledger_by_key)))
        missing_keys = tuple(sorted(set(ledger_by_key) - set(physical_by_key)))

        actual_bytes = sum(item.size_bytes for item in physical_items)
        ledger_bytes = sum(item.size_bytes for item in ledger_items)
        diff_bytes = actual_bytes - ledger_bytes

        missing_referenced_count = sum(
            1 for key in missing_keys if ledger_by_key[key].ref_count > 0
        )
        marked_orphans_count = sum(1 for item in ledger_items if item.status == "marked_orphan")
        total_orphan_signals = marked_orphans_count + len(untracked_keys)

        await self._ledger.record_reconciliation_snapshot(
            diff_bytes=diff_bytes,
            orphaned_objects_count=total_orphan_signals,
            missing_referenced_objects_count=missing_referenced_count,
            checked_at=ref_now,
        )
        metrics = await self._ledger.get_usage_metrics(ref_now)
        warnings = self.evaluate_warnings(metrics, reconciliation_diff_bytes=diff_bytes)

        return ReconciliationReport(
            ledger_bytes=ledger_bytes,
            actual_store_bytes=actual_bytes,
            bytes_difference=diff_bytes,
            ledger_object_count=len(ledger_items),
            actual_store_object_count=len(physical_items),
            untracked_keys=untracked_keys,
            missing_keys=missing_keys,
            expired_reservations_reconciled=len(expired),
            warnings=warnings,
            checked_at=ref_now,
        )
