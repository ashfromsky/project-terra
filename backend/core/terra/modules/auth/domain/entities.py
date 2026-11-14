"""Auth domain entities."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GitHubProfile:
    """Verified user identity returned by GitHub OAuth."""

    github_id: int
    github_login: str
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class User:
    """Authenticated TERRA user anchored to an immutable GitHub ID."""

    id: UUID
    github_id: int
    github_login: str
    display_name: str | None
    avatar_url: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Validated claims extracted from a bearer or cookie session token."""

    user_id: UUID
    github_id: int
