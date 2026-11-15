"""SQLAlchemy persistence adapter for IngestionOperationRepository."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from terra.modules.data_sources.domain.entities import IngestionOperationRecord
from terra.modules.data_sources.infrastructure.models import IngestionOperationModel


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_domain(model: IngestionOperationModel) -> IngestionOperationRecord:
    return IngestionOperationRecord(
        id=model.id,
        owner_id=model.owner_id,
        region_id=model.region_id,
        ghs_job_id=model.ghs_job_id,
        provider=model.provider,
        product=model.product,
        status=model.status,
        progress_pct=model.progress_pct,
        dataset_id=model.dataset_id,
        error_message=model.error_message,
        error_category=model.error_category,
        request_summary=dict(model.request_summary or {}),
        dataset_summary=dict(model.dataset_summary) if model.dataset_summary is not None else None,
        created_at=_normalize_dt(model.created_at),
        updated_at=_normalize_dt(model.updated_at),
    )


class SqlAlchemyIngestionOperationRepository:
    """Async SQLAlchemy repository for Core ingestion operation tracking records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: IngestionOperationRecord) -> IngestionOperationRecord:
        now = datetime.now(UTC)
        model = IngestionOperationModel(
            id=record.id,
            owner_id=record.owner_id,
            region_id=record.region_id,
            ghs_job_id=record.ghs_job_id,
            provider=record.provider,
            product=record.product,
            status=record.status,
            progress_pct=record.progress_pct,
            dataset_id=record.dataset_id,
            error_message=record.error_message,
            error_category=record.error_category,
            request_summary=dict(record.request_summary),
            dataset_summary=(
                dict(record.dataset_summary) if record.dataset_summary is not None else None
            ),
            created_at=record.created_at or now,
            updated_at=record.updated_at or now,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, operation_id: UUID) -> IngestionOperationRecord | None:
        stmt = select(IngestionOperationModel).where(IngestionOperationModel.id == operation_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def list_by_owner(self, owner_id: UUID) -> list[IngestionOperationRecord]:
        stmt = (
            select(IngestionOperationModel)
            .where(IngestionOperationModel.owner_id == owner_id)
            .order_by(IngestionOperationModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(item) for item in result.scalars().all()]

    async def update(self, record: IngestionOperationRecord) -> IngestionOperationRecord:
        stmt = select(IngestionOperationModel).where(IngestionOperationModel.id == record.id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise LookupError(f"Ingestion operation {record.id} not found")

        model.status = record.status
        model.progress_pct = record.progress_pct
        model.dataset_id = record.dataset_id
        model.error_message = record.error_message
        model.error_category = record.error_category
        model.dataset_summary = (
            dict(record.dataset_summary) if record.dataset_summary is not None else None
        )
        model.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)
