"""Persistence contract for ScientificAssessment entities."""

from typing import Protocol
from uuid import UUID

from terra.modules.assessments.domain.entities import ScientificAssessment


class AssessmentRepository(Protocol):
    """Async repository port for scientific assessment storage and worker claiming."""

    async def create(self, assessment: ScientificAssessment) -> ScientificAssessment:
        """Persist a new ScientificAssessment record."""
        ...

    async def get_by_id(self, assessment_id: UUID) -> ScientificAssessment | None:
        """Fetch an assessment by ID or return None."""
        ...

    async def list_by_owner(self, owner_id: UUID) -> list[ScientificAssessment]:
        """List all assessments owned by the given user ordered newest first."""
        ...

    async def update(self, assessment: ScientificAssessment) -> ScientificAssessment:
        """Persist state and result updates on an existing ScientificAssessment."""
        ...

    async def claim_next_queued(self) -> ScientificAssessment | None:
        """Atomically claim the oldest queued assessment and mark it running."""
        ...
