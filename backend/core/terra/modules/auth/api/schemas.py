"""Pydantic schemas for GitHub OAuth and user session responses."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from terra.api.schemas import CamelModel
from terra.modules.auth.domain.entities import User


class UserResponse(CamelModel):
    """Public profile representation of an authenticated TERRA user."""

    id: UUID
    github_id: int
    github_login: str
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        """Map a domain User entity to its API response schema."""
        return cls(
            id=user.id,
            github_id=user.github_id,
            github_login=user.github_login,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            email=user.email,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class GitHubLoginResponse(CamelModel):
    """GitHub authorization URL response for SPA-initiated OAuth."""

    authorize_url: str
    provider: Literal["github"] = "github"


class AuthCallbackResponse(CamelModel):
    """Session payload returned after successful GitHub OAuth callback."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse


class LogoutResponse(CamelModel):
    """Confirmation payload after clearing the session cookie."""

    status: Literal["logged_out"] = "logged_out"
