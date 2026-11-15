"""SQLAlchemy implementations of DatasetRepository and JobRepository ports."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from geospatial_harmonization.domain.exceptions import ErrorCategory
from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, JobStatus
from geospatial_harmonization.domain.models.temporal import require_tz_aware
from geospatial_harmonization.infrastructure.database.codec import (
    decode_dataset,
    decode_plan,
    encode_dataset,
    encode_plan,
    ensure_utc,
)
from geospatial_harmonization.infrastructure.database.models import (
    GhsAssetModel,
    GhsDatasetModel,
    GhsHarmonizationJobModel,
)

_JOB_STATUSES: dict[str, JobStatus] = {
    "pending": "pending",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}

_ERROR_CATEGORIES: dict[str, ErrorCategory] = {
    "authentication": "authentication",
    "authorization": "authorization",
    "validation": "validation",
    "network": "network",
    "provider": "provider",
    "provider_disabled": "provider_disabled",
    "processing": "processing",
    "storage": "storage",
    "cancelled": "cancelled",
    "unknown": "unknown",
}


def _to_job(row: GhsHarmonizationJobModel) -> HarmonizationJob:
    status_val = _JOB_STATUSES.get(row.status)
    if status_val is None:
        raise ValueError(f"Unknown persisted job status: {row.status!r}")
    err_cat = (
        _ERROR_CATEGORIES.get(row.error_category, "unknown")
        if row.error_category is not None
        else None
    )
    return HarmonizationJob(
        job_id=UUID(row.id),
        plan=decode_plan(row.plan_json),
        status=status_val,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        locked_by=row.locked_by,
        lease_expires_at=(
            ensure_utc(row.lease_expires_at) if row.lease_expires_at is not None else None
        ),
        dataset_id=UUID(row.dataset_id) if row.dataset_id is not None else None,
        error_message=row.error_message,
        error_category=err_cat,
        next_retry_at=(ensure_utc(row.next_retry_at) if row.next_retry_at is not None else None),
        progress_pct=row.progress_pct,
        idempotency_key=row.idempotency_key,
    )


class SqlAlchemyDatasetRepository:
    """DatasetRepository adapter persisting SpatialDataset metadata and asset inventory."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def save(self, dataset: SpatialDataset) -> None:
        payload = encode_dataset(dataset)
        created_at = ensure_utc(dataset.provenance.retrieved_at)
        assets = [
            GhsAssetModel(
                dataset_id=str(dataset.dataset_id),
                asset_id=asset.asset_id,
                uri=asset.uri,
                data_format=asset.data_format,
                media_type=asset.media_type,
                checksum_sha256=asset.checksum_sha256,
                size_bytes=asset.size_bytes,
            )
            for asset in dataset.assets
        ]
        async with self._sessions() as session, session.begin():
            existing = await session.get(GhsDatasetModel, str(dataset.dataset_id))
            if existing is None:
                session.add(
                    GhsDatasetModel(
                        id=str(dataset.dataset_id),
                        source_id=dataset.source_id,
                        provider=dataset.provider,
                        product=dataset.product,
                        payload_json=payload,
                        created_at=created_at,
                        assets=assets,
                    )
                )
            else:
                existing.source_id = dataset.source_id
                existing.provider = dataset.provider
                existing.product = dataset.product
                existing.payload_json = payload
                existing.created_at = created_at
                existing.assets = assets

    async def get_by_id(self, dataset_id: UUID) -> SpatialDataset | None:
        async with self._sessions() as session:
            row = await session.get(GhsDatasetModel, str(dataset_id))
        return decode_dataset(row.payload_json) if row is not None else None

    async def find_by_source(
        self, provider: str, product: str, source_id: str
    ) -> SpatialDataset | None:
        stmt = (
            select(GhsDatasetModel)
            .where(
                GhsDatasetModel.provider == provider,
                GhsDatasetModel.product == product,
                GhsDatasetModel.source_id == source_id,
            )
            .order_by(GhsDatasetModel.created_at.desc(), GhsDatasetModel.id.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
        return decode_dataset(row.payload_json) if row is not None else None

    async def list_recent(
        self, limit: int = 50, provider: str | None = None
    ) -> tuple[SpatialDataset, ...]:
        if limit < 1:
            return ()
        stmt = select(GhsDatasetModel).order_by(
            GhsDatasetModel.created_at.desc(), GhsDatasetModel.id.desc()
        )
        if provider is not None:
            stmt = stmt.where(GhsDatasetModel.provider == provider)
        stmt = stmt.limit(limit)
        async with self._sessions() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return tuple(decode_dataset(row.payload_json) for row in rows)


def build_claim_statement(
    now_utc: datetime, *, skip_locked: bool = False
) -> Select[GhsHarmonizationJobModel]:
    """Build the oldest-eligible job claim SELECT, optionally with FOR UPDATE SKIP LOCKED."""
    eligible = or_(
        and_(
            GhsHarmonizationJobModel.status == "pending",
            or_(
                GhsHarmonizationJobModel.next_retry_at.is_(None),
                GhsHarmonizationJobModel.next_retry_at <= now_utc,
            ),
        ),
        and_(
            GhsHarmonizationJobModel.status == "running",
            GhsHarmonizationJobModel.lease_expires_at <= now_utc,
            GhsHarmonizationJobModel.attempt < GhsHarmonizationJobModel.max_attempts,
        ),
    )
    stmt = (
        select(GhsHarmonizationJobModel)
        .where(eligible)
        .order_by(GhsHarmonizationJobModel.created_at.asc(), GhsHarmonizationJobModel.id.asc())
        .limit(1)
    )
    return stmt.with_for_update(skip_locked=True) if skip_locked else stmt


class SqlAlchemyJobRepository:
    """JobRepository adapter using PostgreSQL FOR UPDATE SKIP LOCKED lease claiming."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create(self, job: HarmonizationJob) -> None:
        model = GhsHarmonizationJobModel(
            id=str(job.job_id),
            provider=job.plan.provider,
            product=job.plan.product,
            status=job.status,
            plan_json=encode_plan(job.plan),
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            locked_by=job.locked_by,
            lease_expires_at=(
                ensure_utc(job.lease_expires_at) if job.lease_expires_at is not None else None
            ),
            dataset_id=str(job.dataset_id) if job.dataset_id is not None else None,
            error_message=job.error_message,
            error_category=job.error_category,
            next_retry_at=(
                ensure_utc(job.next_retry_at) if job.next_retry_at is not None else None
            ),
            progress_pct=job.progress_pct,
            idempotency_key=job.idempotency_key,
            created_at=ensure_utc(job.created_at),
            updated_at=ensure_utc(job.updated_at),
        )
        async with self._sessions() as session, session.begin():
            session.add(model)

    async def get_by_id(self, job_id: UUID) -> HarmonizationJob | None:
        async with self._sessions() as session:
            row = await session.get(GhsHarmonizationJobModel, str(job_id))
        return _to_job(row) if row is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> HarmonizationJob | None:
        stmt = (
            select(GhsHarmonizationJobModel)
            .where(GhsHarmonizationJobModel.idempotency_key == idempotency_key)
            .order_by(
                GhsHarmonizationJobModel.created_at.desc(),
                GhsHarmonizationJobModel.id.desc(),
            )
            .limit(1)
        )
        async with self._sessions() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
        return _to_job(row) if row is not None else None

    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int, now: datetime
    ) -> HarmonizationJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be > 0")
        require_tz_aware(now, "now")
        now_utc = ensure_utc(now)
        lease_until = now_utc + timedelta(seconds=lease_seconds)

        for _ in range(3):
            async with self._sessions() as session, session.begin():
                use_pg_lock = session.bind is not None and session.bind.dialect.name == "postgresql"
                stmt = build_claim_statement(now_utc, skip_locked=use_pg_lock)
                cand = (await session.execute(stmt)).scalar_one_or_none()
                if cand is None:
                    return None
                next_attempt = cand.attempt + 1
                next_updated = max(now_utc, ensure_utc(cand.created_at))
                upd = (
                    update(GhsHarmonizationJobModel)
                    .where(
                        GhsHarmonizationJobModel.id == cand.id,
                        GhsHarmonizationJobModel.status == cand.status,
                        GhsHarmonizationJobModel.attempt == cand.attempt,
                    )
                    .values(
                        status="running",
                        attempt=next_attempt,
                        locked_by=worker_id,
                        lease_expires_at=lease_until,
                        next_retry_at=None,
                        progress_pct=0,
                        updated_at=next_updated,
                    )
                )
                result = await session.execute(upd)
                if getattr(result, "rowcount", 0) == 1:
                    claimed = await session.get(
                        GhsHarmonizationJobModel, cand.id, populate_existing=True
                    )
                    return _to_job(claimed) if claimed is not None else None
        return None

    async def update_progress(self, job_id: UUID, progress_pct: int, updated_at: datetime) -> None:
        if not 0 <= progress_pct <= 100:
            raise ValueError("progress_pct must lie within [0, 100]")
        require_tz_aware(updated_at, "updated_at")
        updated_utc = ensure_utc(updated_at)
        async with self._sessions() as session, session.begin():
            row = await session.get(GhsHarmonizationJobModel, str(job_id))
            if row is None:
                raise LookupError(f"Job '{job_id}' not found")
            if row.status in ("succeeded", "failed", "cancelled"):
                return
            row.progress_pct = progress_pct
            row.updated_at = max(updated_utc, ensure_utc(row.created_at))

    async def cancel(
        self, job_id: UUID, cancelled_at: datetime, reason: str = "Cancelled by request"
    ) -> HarmonizationJob | None:
        require_tz_aware(cancelled_at, "cancelled_at")
        cancelled_utc = ensure_utc(cancelled_at)
        async with self._sessions() as session, session.begin():
            row = await session.get(GhsHarmonizationJobModel, str(job_id))
            if row is None:
                return None
            if row.status in ("succeeded", "failed", "cancelled"):
                return _to_job(row)
            row.status = "cancelled"
            row.locked_by = None
            row.lease_expires_at = None
            row.next_retry_at = None
            row.error_category = "cancelled"
            row.error_message = reason
            row.updated_at = max(cancelled_utc, ensure_utc(row.created_at))
            await session.flush()
            return _to_job(row)

    async def mark_succeeded(self, job_id: UUID, dataset_id: UUID, completed_at: datetime) -> None:
        require_tz_aware(completed_at, "completed_at")
        completed_utc = ensure_utc(completed_at)
        async with self._sessions() as session, session.begin():
            row = await session.get(GhsHarmonizationJobModel, str(job_id))
            if row is None:
                raise LookupError(f"Job '{job_id}' not found")
            if row.status == "cancelled":
                return
            row.status = "succeeded"
            row.dataset_id = str(dataset_id)
            row.locked_by = None
            row.lease_expires_at = None
            row.error_message = None
            row.error_category = None
            row.next_retry_at = None
            row.progress_pct = 100
            row.updated_at = max(completed_utc, ensure_utc(row.created_at))

    async def mark_failed(
        self,
        job_id: UUID,
        error_message: str,
        failed_at: datetime,
        *,
        retryable: bool = True,
        error_category: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        require_tz_aware(failed_at, "failed_at")
        if next_retry_at is not None:
            require_tz_aware(next_retry_at, "next_retry_at")
        failed_utc = ensure_utc(failed_at)
        async with self._sessions() as session, session.begin():
            row = await session.get(GhsHarmonizationJobModel, str(job_id))
            if row is None:
                raise LookupError(f"Job '{job_id}' not found")
            if row.status == "cancelled":
                return
            should_retry = retryable and row.attempt < row.max_attempts
            row.status = "pending" if should_retry else "failed"
            row.locked_by = None
            row.lease_expires_at = None
            row.error_message = error_message
            row.error_category = error_category
            row.next_retry_at = (
                ensure_utc(next_retry_at) if (should_retry and next_retry_at is not None) else None
            )
            row.updated_at = max(failed_utc, ensure_utc(row.created_at))
