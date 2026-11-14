"""Repository contract for user persistence."""

from typing import Protocol
from uuid import UUID

from terra.modules.auth.domain.entities import GitHubProfile, User


class UserRepository(Protocol):
    """Persistence port for user identities."""

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by internal UUID, or None if not found."""
        ...

    async def get_by_github_id(self, github_id: int) -> User | None:
        """Return a user by immutable GitHub numeric ID, or None if not found."""
        ...

    async def upsert_by_github_id(self, profile: GitHubProfile) -> User:
        """Create or update a user matched by immutable GitHub ID."""
        ...
