"""SQLAlchemy implementation of AssessmentRepository."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from terra.modules.assessments.domain.entities import (
    AssessmentLifecycleStatus,
    ScientificAssessment,
)
from terra.modules.assessments.infrastructure.models import AssessmentModel


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_utc_opt(value: datetime | None) -> datetime | None:
    return _normalize_utc(value) if value is not None else None


def _to_domain(model: AssessmentModel) -> ScientificAssessment:
    return ScientificAssessment(
        id=model.id,
        owner_id=model.owner_id,
        region_id=model.region_id,
        title=model.title,
        status=cast(AssessmentLifecycleStatus, model.status),
        request_config=dict(model.request_config),
        ghs_dataset_ids=list(model.ghs_dataset_ids),
        inline_datasets=list(model.inline_datasets),
        result_payload=dict(model.result_payload) if model.result_payload is not None else None,
        artifact_paths=dict(model.artifact_paths),
        error_message=model.error_message,
        created_at=_normalize_utc(model.created_at),
        updated_at=_normalize_utc(model.updated_at),
        completed_at=_normalize_utc_opt(model.completed_at),
    )


def _apply_fields(model: AssessmentModel, assessment: ScientificAssessment) -> None:
    model.region_id = assessment.region_id
    model.title = assessment.title
    model.status = assessment.status
    model.request_config = dict(assessment.request_config)
    model.ghs_dataset_ids = list(assessment.ghs_dataset_ids)
    model.inline_datasets = list(assessment.inline_datasets)
    model.result_payload = (
        dict(assessment.result_payload) if assessment.result_payload is not None else None
    )
    model.artifact_paths = dict(assessment.artifact_paths)
    model.error_message = assessment.error_message
    model.updated_at = assessment.updated_at
    model.completed_at = assessment.completed_at


class SqlAlchemyAssessmentRepository:
    """Async SQLAlchemy persistence adapter for AssessmentRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_model(self, assessment_id: UUID) -> AssessmentModel | None:
        res = await self._session.execute(
            select(AssessmentModel).where(AssessmentModel.id == assessment_id)
        )
        return res.scalar_one_or_none()

    async def create(self, assessment: ScientificAssessment) -> ScientificAssessment:
        """Persist a new ScientificAssessment record."""
        model = AssessmentModel(
            id=assessment.id,
            owner_id=assessment.owner_id,
            created_at=assessment.created_at,
        )
        _apply_fields(model, assessment)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, assessment_id: UUID) -> ScientificAssessment | None:
        """Fetch an assessment by ID or return None."""
        model = await self._get_model(assessment_id)
        return _to_domain(model) if model is not None else None

    async def list_by_owner(self, owner_id: UUID) -> list[ScientificAssessment]:
        """List all assessments owned by a user ordered newest first."""
        stmt = (
            select(AssessmentModel)
            .where(AssessmentModel.owner_id == owner_id)
            .order_by(AssessmentModel.created_at.desc())
        )
        res = await self._session.execute(stmt)
        return [_to_domain(m) for m in res.scalars().all()]

    async def update(self, assessment: ScientificAssessment) -> ScientificAssessment:
        """Persist state and result updates on an existing ScientificAssessment."""
        model = await self._get_model(assessment.id)
        if model is None:
            raise LookupError(f"Assessment {assessment.id} not found")
        _apply_fields(model, assessment)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)

    async def claim_next_queued(self) -> ScientificAssessment | None:
        """Atomically claim the oldest queued assessment, preserving PostgreSQL SKIP LOCKED."""
        bind = self._session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else "sqlite"
        now = datetime.now(UTC)

        if dialect_name == "sqlite":
            stmt = (
                select(AssessmentModel.id)
                .where(AssessmentModel.status == "queued")
                .order_by(AssessmentModel.created_at.asc())
                .limit(1)
            )
            candidate_id = (await self._session.execute(stmt)).scalar_one_or_none()
            if candidate_id is None:
                return None
            claim_stmt = (
                update(AssessmentModel)
                .where(AssessmentModel.id == candidate_id, AssessmentModel.status == "queued")
                .values(status="running", updated_at=now)
            )
            claim_res = await self._session.execute(claim_stmt)
            rowcount = getattr(claim_res, "rowcount", 0) or 0
            if rowcount != 1:
                await self._session.rollback()
                return None
            await self._session.commit()
            claimed = await self._get_model(candidate_id)
            return _to_domain(claimed) if claimed is not None else None

        pg_stmt = (
            select(AssessmentModel)
            .where(AssessmentModel.status == "queued")
            .order_by(AssessmentModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        model = (await self._session.execute(pg_stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.status = "running"
        model.updated_at = now
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)
