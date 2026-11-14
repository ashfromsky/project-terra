"""Repository contract for Region persistence."""

from typing import Protocol
from uuid import UUID

from terra.modules.regions.domain.entities import Region


class RegionRepository(Protocol):
    """Persistence port for user-owned geographic regions."""

    async def create(self, region: Region) -> Region:
        """Persist a new Region and return the stored entity."""
        ...

    async def get_by_id(self, region_id: UUID) -> Region | None:
        """Fetch a Region by ID or return None."""
        ...

    async def list_by_owner(self, owner_id: UUID) -> list[Region]:
        """List all Regions owned by a given user ordered by creation time."""
        ...

    async def update(self, region: Region) -> Region:
        """Persist updates to an existing Region."""
        ...

    async def delete(self, region_id: UUID) -> None:
        """Delete a Region by ID."""
        ...
