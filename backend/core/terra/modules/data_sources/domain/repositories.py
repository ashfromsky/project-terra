"""Persistence contract for Core ingestion operation records."""

from typing import Protocol
from uuid import UUID

from terra.modules.data_sources.domain.entities import IngestionOperationRecord


class IngestionOperationRepository(Protocol):
    """Async repository port for storing user ingestion operations."""

    async def create(self, record: IngestionOperationRecord) -> IngestionOperationRecord:
        """Persist a new ingestion operation record."""
        ...

    async def get_by_id(self, operation_id: UUID) -> IngestionOperationRecord | None:
        """Retrieve an ingestion operation record by identifier."""
        ...

    async def list_by_owner(self, owner_id: UUID) -> list[IngestionOperationRecord]:
        """List all ingestion operations owned by the user, newest first."""
        ...

    async def update(self, record: IngestionOperationRecord) -> IngestionOperationRecord:
        """Update status, dataset reference, or error fields on an operation."""
        ...
