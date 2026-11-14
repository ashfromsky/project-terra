"""SQLAlchemy implementation of the transactional StorageLedgerRepository port."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from geospatial_harmonization.domain.exceptions import (
    ObjectTooLargeError,
    StorageBudgetExceededError,
    StorageImmutabilityError,
    StorageIntegrityError,
    StorageReservationError,
)
from geospatial_harmonization.domain.models.dataset import DataFormat
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    ObjectStatus,
    ReferenceKind,
    ReservationStatus,
    StorageObjectRecord,
    StorageReservation,
    StorageUsageMetricsSnapshot,
    StorageZone,
    ZoneUsageSummary,
)
from geospatial_harmonization.domain.models.temporal import require_tz_aware
from geospatial_harmonization.infrastructure.database.codec import ensure_utc
from geospatial_harmonization.infrastructure.database.models import (
    GhsStorageAssetRefModel,
    GhsStorageAuditEventModel,
    GhsStorageLedgerStateModel,
    GhsStorageObjectModel,
    GhsStorageReservationModel,
)

_LEDGER_ROW_ID = "default"
_SQLITE_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    WeakKeyDictionary()
)

_VALID_ZONES: dict[str, StorageZone] = {
    "raw": "raw",
    "intermediate": "intermediate",
    "derived": "derived",
}
_VALID_OBJ_STATUSES: dict[str, ObjectStatus] = {
    "active": "active",
    "marked_orphan": "marked_orphan",
    "deleting": "deleting",
    "deleted": "deleted",
}
_VALID_RES_STATUSES: dict[str, ReservationStatus] = {
    "active": "active",
    "committed": "committed",
    "released": "released",
    "expired": "expired",
    "failed": "failed",
}
_VALID_FORMATS: dict[str, DataFormat] = {
    "geotiff": "geotiff",
    "netcdf": "netcdf",
    "zarr": "zarr",
    "hdf4": "hdf4",
    "hdf5": "hdf5",
    "json": "json",
    "csv": "csv",
    "unknown": "unknown",
}


def build_ledger_lock_statement(*, for_update: bool = False) -> Select[GhsStorageLedgerStateModel]:
    """Build the singleton storage ledger SELECT statement, optionally with FOR UPDATE."""
    stmt = select(GhsStorageLedgerStateModel).where(GhsStorageLedgerStateModel.id == _LEDGER_ROW_ID)
    return stmt.with_for_update() if for_update else stmt


def _to_object_record(row: GhsStorageObjectModel) -> StorageObjectRecord:
    zone = _VALID_ZONES.get(row.zone)
    status = _VALID_OBJ_STATUSES.get(row.status)
    data_format = _VALID_FORMATS.get(row.data_format, "unknown")
    if zone is None or status is None:
        raise StorageIntegrityError(f"Corrupt storage object row '{row.object_key}'")
    return StorageObjectRecord(
        object_key=row.object_key,
        zone=zone,
        content_sha256=row.content_sha256,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        data_format=data_format,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
        original_size_bytes=row.original_size_bytes,
        compression_codec=row.compression_codec,
        ref_count=row.ref_count,
        status=status,
        marked_orphan_at=(
            ensure_utc(row.marked_orphan_at) if row.marked_orphan_at is not None else None
        ),
        expires_at=ensure_utc(row.expires_at) if row.expires_at is not None else None,
    )


def _to_reservation(row: GhsStorageReservationModel) -> StorageReservation:
    zone = _VALID_ZONES.get(row.zone)
    status = _VALID_RES_STATUSES.get(row.status)
    if zone is None or status is None:
        raise StorageReservationError(f"Corrupt reservation row '{row.id}'")
    return StorageReservation(
        reservation_id=UUID(row.id),
        job_id=row.job_id,
        operation=row.operation,
        zone=zone,
        reserved_bytes=row.reserved_bytes,
        status=status,
        created_at=ensure_utc(row.created_at),
        expires_at=ensure_utc(row.expires_at),
        actual_bytes=row.actual_bytes,
        reconciled_at=(ensure_utc(row.reconciled_at) if row.reconciled_at is not None else None),
        notes=row.notes,
    )


def _adjust_zone_bytes(ledger: GhsStorageLedgerStateModel, zone: StorageZone, delta: int) -> None:
    if zone == "raw":
        ledger.raw_bytes = max(0, ledger.raw_bytes + delta)
    elif zone == "intermediate":
        ledger.intermediate_bytes = max(0, ledger.intermediate_bytes + delta)
    else:
        ledger.derived_bytes = max(0, ledger.derived_bytes + delta)


def _get_sqlite_lock(session: AsyncSession) -> asyncio.Lock | None:
    bind = session.bind
    if bind is None or bind.dialect.name != "sqlite":
        return None
    loop = asyncio.get_running_loop()
    per_loop = _SQLITE_LOCKS.setdefault(loop, {})
    target = getattr(bind, "engine", bind)
    url_key = str(getattr(target, "url", id(bind)))
    lock = per_loop.get(url_key)
    if lock is None:
        lock = asyncio.Lock()
        per_loop[url_key] = lock
    return lock


async def _ensure_ledger_row_in_tx(session: AsyncSession, now_utc: datetime) -> None:
    values: dict[str, Any] = {
        "id": _LEDGER_ROW_ID,
        "total_stored_bytes": 0,
        "object_count": 0,
        "raw_bytes": 0,
        "intermediate_bytes": 0,
        "derived_bytes": 0,
        "reserved_bytes": 0,
        "compression_savings_bytes": 0,
        "deduplication_savings_bytes": 0,
        "cleanup_deleted_objects": 0,
        "cleanup_reclaimed_bytes": 0,
        "failed_uploads_count": 0,
        "orphaned_objects_count": 0,
        "missing_referenced_objects_count": 0,
        "last_reconciliation_diff_bytes": None,
        "last_reconciliation_at": None,
        "version": 0,
        "updated_at": now_utc,
    }
    bind = session.bind
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        await session.execute(
            pg_insert(GhsStorageLedgerStateModel)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        return
    if dialect == "sqlite":
        await session.execute(
            sqlite_insert(GhsStorageLedgerStateModel)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        return
    existing = await session.get(GhsStorageLedgerStateModel, _LEDGER_ROW_ID)
    if existing is None:
        session.add(GhsStorageLedgerStateModel(**values))
        await session.flush()


class SqlAlchemyStorageLedgerRepository:
    """Transactional storage quota ledger supporting PostgreSQL FOR UPDATE and SQLite locking."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @asynccontextmanager
    async def _locked_ledger(
        self, now_utc: datetime
    ) -> AsyncIterator[tuple[AsyncSession, GhsStorageLedgerStateModel]]:
        async with self._sessions() as probe:
            lock = _get_sqlite_lock(probe)

        if lock is not None:
            async with lock, self._sessions() as session, session.begin():
                await _ensure_ledger_row_in_tx(session, now_utc)
                ledger = (
                    await session.execute(build_ledger_lock_statement(for_update=False))
                ).scalar_one()
                yield session, ledger
            return

        async with self._sessions() as session, session.begin():
            await _ensure_ledger_row_in_tx(session, now_utc)
            use_pg = session.bind is not None and session.bind.dialect.name == "postgresql"
            ledger = (
                await session.execute(build_ledger_lock_statement(for_update=use_pg))
            ).scalar_one()
            yield session, ledger

    async def ensure_ledger_initialized(self, now: datetime) -> None:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc):
            return

    def _add_audit(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        zone: StorageZone | None,
        object_key: str | None,
        bytes_delta: int,
        saved_bytes: int,
        details: dict[str, object],
        now_utc: datetime,
    ) -> None:
        session.add(
            GhsStorageAuditEventModel(
                event_type=event_type,
                zone=zone,
                object_key=object_key,
                bytes_delta=bytes_delta,
                saved_bytes=saved_bytes,
                details_json=details,
                created_at=now_utc,
            )
        )

    async def _expire_stale_in_tx(
        self,
        session: AsyncSession,
        ledger: GhsStorageLedgerStateModel,
        now_utc: datetime,
    ) -> tuple[StorageReservation, ...]:
        stmt = (
            select(GhsStorageReservationModel)
            .where(
                GhsStorageReservationModel.status == "active",
                GhsStorageReservationModel.expires_at <= now_utc,
            )
            .order_by(GhsStorageReservationModel.created_at.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        expired: list[StorageReservation] = []
        for row in rows:
            row.status = "expired"
            row.reconciled_at = now_utc
            ledger.reserved_bytes = max(0, ledger.reserved_bytes - row.reserved_bytes)
            ledger.version += 1
            ledger.updated_at = now_utc
            res = _to_reservation(row)
            expired.append(res)
            self._add_audit(
                session,
                event_type="reservation_expired",
                zone=res.zone,
                object_key=None,
                bytes_delta=-row.reserved_bytes,
                saved_bytes=0,
                details={"reservation_id": row.id, "job_id": row.job_id},
                now_utc=now_utc,
            )
        return tuple(expired)

    async def reserve_capacity(
        self,
        reservation: StorageReservation,
        *,
        budget_bytes: int,
        hard_limit_threshold: float,
        max_object_bytes: int,
        max_job_output_bytes: int,
        now: datetime,
    ) -> StorageReservation:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        if reservation.status != "active":
            raise StorageReservationError("New reservation must start with status='active'")

        async with self._locked_ledger(now_utc) as (session, ledger):
            await self._expire_stale_in_tx(session, ledger, now_utc)

            if reservation.reserved_bytes > max_object_bytes:
                raise ObjectTooLargeError(
                    f"Requested object size {reservation.reserved_bytes} bytes exceeds "
                    f"max object limit of {max_object_bytes} bytes",
                    requested_bytes=reservation.reserved_bytes,
                    limit_bytes=max_object_bytes,
                    scope="object",
                )

            if reservation.job_id is not None and reservation.zone != "raw":
                active_job_stmt = select(
                    func.coalesce(func.sum(GhsStorageReservationModel.reserved_bytes), 0)
                ).where(
                    GhsStorageReservationModel.job_id == reservation.job_id,
                    GhsStorageReservationModel.status == "active",
                    GhsStorageReservationModel.zone != "raw",
                )
                active_for_job = int((await session.execute(active_job_stmt)).scalar_one())
                projected_job_bytes = active_for_job + reservation.reserved_bytes
                if projected_job_bytes > max_job_output_bytes:
                    raise ObjectTooLargeError(
                        f"Job '{reservation.job_id}' output reservation {projected_job_bytes} "
                        f"bytes exceeds max job output limit of {max_job_output_bytes} bytes",
                        requested_bytes=projected_job_bytes,
                        limit_bytes=max_job_output_bytes,
                        scope="job_output",
                    )

            hard_limit_bytes = int(budget_bytes * hard_limit_threshold)
            allocated = ledger.total_stored_bytes + ledger.reserved_bytes
            available = max(0, hard_limit_bytes - allocated)
            if allocated + reservation.reserved_bytes > hard_limit_bytes:
                raise StorageBudgetExceededError(
                    f"Storage budget exceeded for zone '{reservation.zone}': "
                    f"requested {reservation.reserved_bytes} bytes, available {available} bytes",
                    requested_bytes=reservation.reserved_bytes,
                    available_bytes=available,
                    budget_bytes=budget_bytes,
                    reserved_bytes=ledger.reserved_bytes,
                    zone=reservation.zone,
                )

            existing = await session.get(
                GhsStorageReservationModel, str(reservation.reservation_id)
            )
            if existing is not None:
                raise StorageReservationError(
                    f"Reservation '{reservation.reservation_id}' already exists"
                )

            session.add(
                GhsStorageReservationModel(
                    id=str(reservation.reservation_id),
                    job_id=reservation.job_id,
                    operation=reservation.operation,
                    zone=reservation.zone,
                    reserved_bytes=reservation.reserved_bytes,
                    actual_bytes=reservation.actual_bytes,
                    status=reservation.status,
                    notes=reservation.notes,
                    created_at=ensure_utc(reservation.created_at),
                    expires_at=ensure_utc(reservation.expires_at),
                    reconciled_at=reservation.reconciled_at,
                )
            )
            ledger.reserved_bytes += reservation.reserved_bytes
            ledger.version += 1
            ledger.updated_at = now_utc
            self._add_audit(
                session,
                event_type="reservation_created",
                zone=reservation.zone,
                object_key=None,
                bytes_delta=reservation.reserved_bytes,
                saved_bytes=0,
                details={
                    "reservation_id": str(reservation.reservation_id),
                    "job_id": reservation.job_id,
                    "operation": reservation.operation,
                },
                now_utc=now_utc,
            )
        return reservation

    async def commit_reservation(
        self, reservation_id: UUID, actual_bytes: int, now: datetime
    ) -> StorageReservation:
        if actual_bytes < 0:
            raise StorageReservationError("actual_bytes must be >= 0")
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, ledger):
            row = await session.get(GhsStorageReservationModel, str(reservation_id))
            if row is None:
                raise StorageReservationError(f"Reservation '{reservation_id}' not found")
            if row.status != "active":
                raise StorageReservationError(
                    f"Reservation '{reservation_id}' has status '{row.status}', cannot commit"
                )
            ledger.reserved_bytes = max(0, ledger.reserved_bytes - row.reserved_bytes)
            ledger.version += 1
            ledger.updated_at = now_utc
            row.status = "committed"
            row.actual_bytes = actual_bytes
            row.reconciled_at = now_utc
            res = _to_reservation(row)
            self._add_audit(
                session,
                event_type="reservation_committed",
                zone=res.zone,
                object_key=None,
                bytes_delta=actual_bytes - row.reserved_bytes,
                saved_bytes=max(0, row.reserved_bytes - actual_bytes),
                details={
                    "reservation_id": row.id,
                    "reserved_bytes": row.reserved_bytes,
                    "actual_bytes": actual_bytes,
                },
                now_utc=now_utc,
            )
            return res

    async def release_reservation(
        self,
        reservation_id: UUID,
        status: Literal["released", "failed"],
        now: datetime,
        reason: str | None = None,
    ) -> StorageReservation:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, ledger):
            row = await session.get(GhsStorageReservationModel, str(reservation_id))
            if row is None:
                raise StorageReservationError(f"Reservation '{reservation_id}' not found")
            if row.status == "committed":
                raise StorageReservationError(
                    f"Reservation '{reservation_id}' is already committed"
                )
            if row.status in ("released", "failed", "expired"):
                return _to_reservation(row)
            ledger.reserved_bytes = max(0, ledger.reserved_bytes - row.reserved_bytes)
            if status == "failed":
                ledger.failed_uploads_count += 1
            ledger.version += 1
            ledger.updated_at = now_utc
            row.status = status
            row.reconciled_at = now_utc
            if reason is not None:
                row.notes = reason
            res = _to_reservation(row)
            self._add_audit(
                session,
                event_type=f"reservation_{status}",
                zone=res.zone,
                object_key=None,
                bytes_delta=-row.reserved_bytes,
                saved_bytes=0,
                details={"reservation_id": row.id, "reason": reason},
                now_utc=now_utc,
            )
            return res

    async def reconcile_expired_reservations(self, now: datetime) -> tuple[StorageReservation, ...]:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, ledger):
            return await self._expire_stale_in_tx(session, ledger, now_utc)

    async def get_reservation(self, reservation_id: UUID) -> StorageReservation | None:
        async with self._sessions() as session:
            row = await session.get(GhsStorageReservationModel, str(reservation_id))
        return _to_reservation(row) if row is not None else None

    async def list_active_reservations(self, now: datetime) -> tuple[StorageReservation, ...]:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        stmt = (
            select(GhsStorageReservationModel)
            .where(
                GhsStorageReservationModel.status == "active",
                GhsStorageReservationModel.expires_at > now_utc,
            )
            .order_by(GhsStorageReservationModel.created_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return tuple(_to_reservation(row) for row in rows)

    async def get_object(self, object_key: str) -> StorageObjectRecord | None:
        async with self._sessions() as session:
            row = await session.get(GhsStorageObjectModel, object_key)
        return _to_object_record(row) if row is not None else None

    async def find_active_by_checksum(
        self, checksum_sha256: str, zone: StorageZone | None = None
    ) -> StorageObjectRecord | None:
        stmt = (
            select(GhsStorageObjectModel)
            .where(
                GhsStorageObjectModel.content_sha256 == checksum_sha256.lower(),
                GhsStorageObjectModel.status == "active",
            )
            .order_by(GhsStorageObjectModel.created_at.asc())
            .limit(1)
        )
        if zone is not None:
            stmt = stmt.where(GhsStorageObjectModel.zone == zone)
        async with self._sessions() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
        return _to_object_record(row) if row is not None else None

    async def _insert_asset_ref_if_missing(
        self, session: AsyncSession, obj_row: GhsStorageObjectModel, ref: AssetReferenceLink
    ) -> bool:
        existing_ref = (
            await session.execute(
                select(GhsStorageAssetRefModel).where(
                    GhsStorageAssetRefModel.object_key == ref.object_key,
                    GhsStorageAssetRefModel.ref_kind == ref.ref_kind,
                    GhsStorageAssetRefModel.ref_owner_id == ref.ref_owner_id,
                    GhsStorageAssetRefModel.asset_id == ref.asset_id,
                )
            )
        ).scalar_one_or_none()
        if existing_ref is not None:
            return False
        session.add(
            GhsStorageAssetRefModel(
                object_key=ref.object_key,
                ref_kind=ref.ref_kind,
                ref_owner_id=ref.ref_owner_id,
                asset_id=ref.asset_id,
                provider=ref.provider,
                product=ref.product,
                metadata_json=dict(ref.metadata),
                created_at=ensure_utc(ref.created_at),
            )
        )
        obj_row.ref_count += 1
        return True

    async def register_object_and_ref(
        self,
        obj: StorageObjectRecord,
        ref: AssetReferenceLink,
        now: datetime,
        *,
        dedup_saved_bytes: int = 0,
    ) -> tuple[StorageObjectRecord, bool]:
        require_tz_aware(now, "now")
        if ref.object_key != obj.object_key:
            raise StorageIntegrityError(
                f"AssetReferenceLink.object_key '{ref.object_key}' "
                f"does not match '{obj.object_key}'"
            )
        now_utc = ensure_utc(now)
        compression_saved = max(0, (obj.original_size_bytes or obj.size_bytes) - obj.size_bytes)
        async with self._locked_ledger(now_utc) as (session, ledger):
            row = await session.get(GhsStorageObjectModel, obj.object_key)
            created_new = False
            if row is None:
                row = GhsStorageObjectModel(
                    object_key=obj.object_key,
                    zone=obj.zone,
                    content_sha256=obj.content_sha256.lower(),
                    size_bytes=obj.size_bytes,
                    original_size_bytes=obj.original_size_bytes,
                    media_type=obj.media_type,
                    data_format=obj.data_format,
                    compression_codec=obj.compression_codec,
                    ref_count=0,
                    status=obj.status,
                    marked_orphan_at=obj.marked_orphan_at,
                    expires_at=obj.expires_at,
                    created_at=ensure_utc(obj.created_at),
                    updated_at=now_utc,
                )
                session.add(row)
                ledger.object_count += 1
                ledger.total_stored_bytes += obj.size_bytes
                _adjust_zone_bytes(ledger, obj.zone, obj.size_bytes)
                ledger.compression_savings_bytes += compression_saved
                created_new = True
            elif row.status == "deleted":
                row.zone = obj.zone
                row.content_sha256 = obj.content_sha256.lower()
                row.size_bytes = obj.size_bytes
                row.original_size_bytes = obj.original_size_bytes
                row.media_type = obj.media_type
                row.data_format = obj.data_format
                row.compression_codec = obj.compression_codec
                row.ref_count = 0
                row.status = "active"
                row.marked_orphan_at = None
                row.expires_at = obj.expires_at
                row.updated_at = now_utc
                ledger.object_count += 1
                ledger.total_stored_bytes += obj.size_bytes
                _adjust_zone_bytes(ledger, obj.zone, obj.size_bytes)
                ledger.compression_savings_bytes += compression_saved
                created_new = True
            else:
                if row.status == "marked_orphan":
                    row.status = "active"
                    row.marked_orphan_at = None
                delta = obj.size_bytes - row.size_bytes
                if delta != 0:
                    row.size_bytes = obj.size_bytes
                    ledger.total_stored_bytes = max(0, ledger.total_stored_bytes + delta)
                    _adjust_zone_bytes(ledger, obj.zone, delta)
                row.updated_at = now_utc

            await self._insert_asset_ref_if_missing(session, row, ref)

            if dedup_saved_bytes > 0:
                ledger.deduplication_savings_bytes += dedup_saved_bytes
                self._add_audit(
                    session,
                    event_type="dedup_reused",
                    zone=obj.zone,
                    object_key=obj.object_key,
                    bytes_delta=0,
                    saved_bytes=dedup_saved_bytes,
                    details={
                        "ref_kind": ref.ref_kind,
                        "ref_owner_id": ref.ref_owner_id,
                        "checksum": obj.content_sha256.lower(),
                    },
                    now_utc=now_utc,
                )
            if created_new:
                self._add_audit(
                    session,
                    event_type="object_registered",
                    zone=obj.zone,
                    object_key=obj.object_key,
                    bytes_delta=obj.size_bytes,
                    saved_bytes=compression_saved,
                    details={"data_format": obj.data_format, "codec": obj.compression_codec},
                    now_utc=now_utc,
                )

            ledger.version += 1
            ledger.updated_at = now_utc
            await session.flush()
            return _to_object_record(row), created_new

    async def add_asset_reference(self, ref: AssetReferenceLink, now: datetime) -> bool:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, ledger):
            obj_row = await session.get(GhsStorageObjectModel, ref.object_key)
            if obj_row is None or obj_row.status == "deleted":
                raise StorageIntegrityError(
                    f"Cannot attach reference to missing object '{ref.object_key}'"
                )
            inserted = await self._insert_asset_ref_if_missing(session, obj_row, ref)
            if not inserted:
                return False
            if obj_row.status == "marked_orphan":
                obj_row.status = "active"
                obj_row.marked_orphan_at = None
            obj_row.updated_at = now_utc
            ledger.version += 1
            ledger.updated_at = now_utc
            return True

    async def remove_asset_references_for_owner(
        self, ref_kind: ReferenceKind, ref_owner_id: str, now: datetime
    ) -> tuple[str, ...]:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, ledger):
            refs = (
                (
                    await session.execute(
                        select(GhsStorageAssetRefModel).where(
                            GhsStorageAssetRefModel.ref_kind == ref_kind,
                            GhsStorageAssetRefModel.ref_owner_id == ref_owner_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not refs:
                return ()
            counts: dict[str, int] = {}
            for ref_row in refs:
                counts[ref_row.object_key] = counts.get(ref_row.object_key, 0) + 1
                await session.delete(ref_row)
            await session.flush()

            for key, removed in counts.items():
                obj_row = await session.get(GhsStorageObjectModel, key)
                if obj_row is not None:
                    obj_row.ref_count = max(0, obj_row.ref_count - removed)
                    obj_row.updated_at = now_utc

            ledger.version += 1
            ledger.updated_at = now_utc
            return tuple(sorted(counts))

    async def has_active_references(self, object_key: str) -> bool:
        stmt = select(func.count(GhsStorageAssetRefModel.id)).where(
            GhsStorageAssetRefModel.object_key == object_key
        )
        async with self._sessions() as session:
            count = int((await session.execute(stmt)).scalar_one())
        return count > 0

    async def mark_object_orphan(
        self, object_key: str, marked_at: datetime
    ) -> StorageObjectRecord | None:
        require_tz_aware(marked_at, "marked_at")
        marked_utc = ensure_utc(marked_at)
        async with self._locked_ledger(marked_utc) as (session, ledger):
            ref_count = int(
                (
                    await session.execute(
                        select(func.count(GhsStorageAssetRefModel.id)).where(
                            GhsStorageAssetRefModel.object_key == object_key
                        )
                    )
                ).scalar_one()
            )
            if ref_count > 0:
                raise StorageImmutabilityError(
                    f"Cannot mark referenced object '{object_key}' as orphan ({ref_count} refs)"
                )
            row = await session.get(GhsStorageObjectModel, object_key)
            if row is None or row.status == "deleted":
                return None
            if row.status != "marked_orphan":
                row.status = "marked_orphan"
                row.marked_orphan_at = marked_utc
                row.updated_at = marked_utc
                ledger.version += 1
                ledger.updated_at = marked_utc
            return _to_object_record(row)

    async def delete_object_record(self, object_key: str, deleted_at: datetime) -> bool:
        require_tz_aware(deleted_at, "deleted_at")
        deleted_utc = ensure_utc(deleted_at)
        async with self._locked_ledger(deleted_utc) as (session, ledger):
            ref_count = int(
                (
                    await session.execute(
                        select(func.count(GhsStorageAssetRefModel.id)).where(
                            GhsStorageAssetRefModel.object_key == object_key
                        )
                    )
                ).scalar_one()
            )
            if ref_count > 0:
                raise StorageImmutabilityError(
                    f"Refusing to delete storage object '{object_key}' with {ref_count} active refs"
                )
            row = await session.get(GhsStorageObjectModel, object_key)
            if row is None or row.status == "deleted":
                return False
            zone = _VALID_ZONES[row.zone]
            reclaimed = row.size_bytes
            row.status = "deleted"
            row.updated_at = deleted_utc
            ledger.object_count = max(0, ledger.object_count - 1)
            ledger.total_stored_bytes = max(0, ledger.total_stored_bytes - reclaimed)
            _adjust_zone_bytes(ledger, zone, -reclaimed)
            ledger.cleanup_deleted_objects += 1
            ledger.cleanup_reclaimed_bytes += reclaimed
            ledger.version += 1
            ledger.updated_at = deleted_utc
            self._add_audit(
                session,
                event_type="object_deleted",
                zone=zone,
                object_key=object_key,
                bytes_delta=-reclaimed,
                saved_bytes=reclaimed,
                details={"reason": "lifecycle_sweep"},
                now_utc=deleted_utc,
            )
            return True

    async def list_objects(
        self, zone: StorageZone | None = None, status: ObjectStatus | None = None
    ) -> tuple[StorageObjectRecord, ...]:
        stmt = select(GhsStorageObjectModel).order_by(GhsStorageObjectModel.object_key.asc())
        if zone is not None:
            stmt = stmt.where(GhsStorageObjectModel.zone == zone)
        if status is not None:
            stmt = stmt.where(GhsStorageObjectModel.status == status)
        else:
            stmt = stmt.where(GhsStorageObjectModel.status != "deleted")
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return tuple(_to_object_record(row) for row in rows)

    async def list_expired_intermediate_objects(
        self, now: datetime
    ) -> tuple[StorageObjectRecord, ...]:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        stmt = (
            select(GhsStorageObjectModel)
            .where(
                GhsStorageObjectModel.zone == "intermediate",
                GhsStorageObjectModel.status == "active",
                GhsStorageObjectModel.ref_count == 0,
                GhsStorageObjectModel.expires_at.is_not(None),
                GhsStorageObjectModel.expires_at <= now_utc,
            )
            .order_by(GhsStorageObjectModel.expires_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return tuple(_to_object_record(row) for row in rows)

    async def list_orphan_sweep_candidates(
        self, marked_before: datetime
    ) -> tuple[StorageObjectRecord, ...]:
        require_tz_aware(marked_before, "marked_before")
        cutoff_utc = ensure_utc(marked_before)
        stmt = (
            select(GhsStorageObjectModel)
            .where(
                GhsStorageObjectModel.status == "marked_orphan",
                GhsStorageObjectModel.ref_count == 0,
                GhsStorageObjectModel.marked_orphan_at.is_not(None),
                GhsStorageObjectModel.marked_orphan_at <= cutoff_utc,
            )
            .order_by(GhsStorageObjectModel.marked_orphan_at.asc())
        )
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return tuple(_to_object_record(row) for row in rows)

    async def record_audit_event(
        self,
        event_type: str,
        zone: StorageZone | None,
        object_key: str | None,
        bytes_delta: int,
        saved_bytes: int,
        details: dict[str, object],
        now: datetime,
    ) -> None:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        async with self._locked_ledger(now_utc) as (session, _ledger):
            self._add_audit(
                session,
                event_type=event_type,
                zone=zone,
                object_key=object_key,
                bytes_delta=bytes_delta,
                saved_bytes=saved_bytes,
                details=details,
                now_utc=now_utc,
            )

    async def record_reconciliation_snapshot(
        self,
        *,
        diff_bytes: int,
        orphaned_objects_count: int,
        missing_referenced_objects_count: int,
        checked_at: datetime,
    ) -> None:
        require_tz_aware(checked_at, "checked_at")
        checked_utc = ensure_utc(checked_at)
        async with self._locked_ledger(checked_utc) as (session, ledger):
            ledger.last_reconciliation_diff_bytes = diff_bytes
            ledger.last_reconciliation_at = checked_utc
            ledger.orphaned_objects_count = orphaned_objects_count
            ledger.missing_referenced_objects_count = missing_referenced_objects_count
            ledger.version += 1
            ledger.updated_at = checked_utc
            self._add_audit(
                session,
                event_type="reconciliation",
                zone=None,
                object_key=None,
                bytes_delta=diff_bytes,
                saved_bytes=0,
                details={
                    "orphaned_objects_count": orphaned_objects_count,
                    "missing_referenced_objects_count": missing_referenced_objects_count,
                },
                now_utc=checked_utc,
            )

    async def get_usage_metrics(self, now: datetime) -> StorageUsageMetricsSnapshot:
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        day_ago = now_utc - timedelta(hours=24)

        async with self._sessions() as session:
            ledger = await session.get(GhsStorageLedgerStateModel, _LEDGER_ROW_ID)

            obj_rows = (
                (
                    await session.execute(
                        select(GhsStorageObjectModel).where(
                            GhsStorageObjectModel.status != "deleted"
                        )
                    )
                )
                .scalars()
                .all()
            )
            res_rows = (
                await session.execute(
                    select(
                        GhsStorageReservationModel.zone,
                        func.coalesce(func.sum(GhsStorageReservationModel.reserved_bytes), 0),
                    )
                    .where(
                        GhsStorageReservationModel.status == "active",
                        GhsStorageReservationModel.expires_at > now_utc,
                    )
                    .group_by(GhsStorageReservationModel.zone)
                )
            ).all()
            dedup_rows = (
                await session.execute(
                    select(
                        GhsStorageAuditEventModel.zone,
                        func.coalesce(func.sum(GhsStorageAuditEventModel.saved_bytes), 0),
                    )
                    .where(GhsStorageAuditEventModel.event_type == "dedup_reused")
                    .group_by(GhsStorageAuditEventModel.zone)
                )
            ).all()
            growth_sum = int(
                (
                    await session.execute(
                        select(
                            func.coalesce(func.sum(GhsStorageAuditEventModel.bytes_delta), 0)
                        ).where(
                            GhsStorageAuditEventModel.created_at >= day_ago,
                            GhsStorageAuditEventModel.event_type.in_(
                                ("object_registered", "object_deleted")
                            ),
                        )
                    )
                ).scalar_one()
            )

        res_by_zone: dict[str, int] = {str(z): int(v) for z, v in res_rows if z is not None}
        dedup_by_zone: dict[str, int] = {str(z): int(v) for z, v in dedup_rows if z is not None}

        counts: dict[StorageZone, int] = {"raw": 0, "intermediate": 0, "derived": 0}
        stored: dict[StorageZone, int] = {"raw": 0, "intermediate": 0, "derived": 0}
        orig: dict[StorageZone, int] = {"raw": 0, "intermediate": 0, "derived": 0}
        comp_saved: dict[StorageZone, int] = {"raw": 0, "intermediate": 0, "derived": 0}
        marked_orphan_count = 0

        for obj_row in obj_rows:
            zone = _VALID_ZONES.get(obj_row.zone)
            if zone is None:
                continue
            counts[zone] += 1
            stored[zone] += obj_row.size_bytes
            raw_orig = (
                obj_row.original_size_bytes
                if obj_row.original_size_bytes is not None
                else obj_row.size_bytes
            )
            orig[zone] += raw_orig
            comp_saved[zone] += max(0, raw_orig - obj_row.size_bytes)
            if obj_row.status == "marked_orphan":
                marked_orphan_count += 1

        zones = {
            zone: ZoneUsageSummary(
                zone=zone,
                object_count=counts[zone],
                stored_bytes=stored[zone],
                reserved_bytes=res_by_zone.get(zone, 0),
                original_bytes=orig[zone],
                compression_saved_bytes=comp_saved[zone],
                dedup_saved_bytes=dedup_by_zone.get(zone, 0),
            )
            for zone in ("raw", "intermediate", "derived")
        }
        zones_typed = cast("dict[StorageZone, ZoneUsageSummary]", zones)

        total_reserved = sum(res_by_zone.values())
        return StorageUsageMetricsSnapshot(
            total_stored_bytes=sum(stored.values()),
            object_count=sum(counts.values()),
            reserved_bytes=total_reserved,
            zones=zones_typed,
            daily_growth_bytes=max(0, growth_sum),
            compression_savings_bytes=sum(comp_saved.values()),
            deduplication_savings_bytes=(
                ledger.deduplication_savings_bytes
                if ledger is not None
                else sum(dedup_by_zone.values())
            ),
            cleanup_deleted_objects=(ledger.cleanup_deleted_objects if ledger is not None else 0),
            cleanup_reclaimed_bytes=(ledger.cleanup_reclaimed_bytes if ledger is not None else 0),
            failed_uploads_count=(ledger.failed_uploads_count if ledger is not None else 0),
            orphaned_objects_count=max(
                marked_orphan_count,
                ledger.orphaned_objects_count if ledger is not None else 0,
            ),
            missing_referenced_objects_count=(
                ledger.missing_referenced_objects_count if ledger is not None else 0
            ),
            last_reconciliation_diff_bytes=(
                ledger.last_reconciliation_diff_bytes if ledger is not None else None
            ),
            last_reconciliation_at=(
                ensure_utc(ledger.last_reconciliation_at)
                if ledger is not None and ledger.last_reconciliation_at is not None
                else None
            ),
        )
