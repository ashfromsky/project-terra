"""Infrastructure port contracts for GitHub OAuth and token signing."""

from typing import Protocol

from terra.modules.auth.domain.entities import (
    AccessTokenClaims,
    GitHubProfile,
    OAuthStateClaims,
    User,
)


class GitHubOAuthClient(Protocol):
    """Port for interacting with GitHub OAuth endpoints."""

    def build_authorize_url(self, state: str) -> str:
        """Build the GitHub authorization redirect URL with CSRF state."""
        ...

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        """Exchange an authorization code for a verified GitHub user profile."""
        ...


class TokenService(Protocol):
    """Port for issuing and verifying OAuth state and session tokens."""

    def issue_oauth_state(
        self, *, redirect_to_frontend: bool = False, return_to: str | None = None
    ) -> str:
        """Issue a short-lived signed OAuth CSRF state token."""
        ...

    def verify_oauth_state(self, state: str) -> OAuthStateClaims:
        """Validate an OAuth CSRF state token and return its claims."""
        ...

    def issue_access_token(self, user: User) -> str:
        """Issue a signed session access token for the given user."""
        ...

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        """Verify a session access token and return parsed claims."""
        ...
