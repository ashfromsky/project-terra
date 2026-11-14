"""Application use cases for GitHub OAuth authentication."""

from dataclasses import dataclass

from terra.modules.auth.domain.entities import User
from terra.modules.auth.domain.exceptions import AuthenticationError
from terra.modules.auth.domain.ports import GitHubOAuthClient, TokenService
from terra.modules.auth.domain.repositories import UserRepository


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Result of completing a GitHub OAuth login."""

    user: User
    access_token: str


class StartGitHubLoginUseCase:
    """Generate a GitHub OAuth authorization URL protected by signed state."""

    def __init__(self, github_client: GitHubOAuthClient, token_service: TokenService) -> None:
        self._github = github_client
        self._tokens = token_service

    def execute(self) -> tuple[str, str]:
        """Return `(authorize_url, state)`."""
        state = self._tokens.issue_oauth_state()
        return self._github.build_authorize_url(state), state


class AuthenticateGitHubCallbackUseCase:
    """Validate OAuth callback state, exchange code, and upsert user by GitHub ID."""

    def __init__(
        self,
        users: UserRepository,
        github_client: GitHubOAuthClient,
        token_service: TokenService,
    ) -> None:
        self._users = users
        self._github = github_client
        self._tokens = token_service

    async def execute(self, code: str, state: str) -> AuthenticatedSession:
        """Complete OAuth callback and return the persisted user and session token."""
        if not code.strip():
            raise AuthenticationError("Missing GitHub authorization code")
        self._tokens.verify_oauth_state(state)
        profile = await self._github.exchange_code_for_profile(code)
        user = await self._users.upsert_by_github_id(profile)
        token = self._tokens.issue_access_token(user)
        return AuthenticatedSession(user=user, access_token=token)


class GetCurrentUserUseCase:
    """Resolve an authenticated user from a session token."""

    def __init__(self, users: UserRepository, token_service: TokenService) -> None:
        self._users = users
        self._tokens = token_service

    async def execute(self, token: str) -> User:
        """Verify access token and load the corresponding user."""
        claims = self._tokens.verify_access_token(token)
        user = await self._users.get_by_id(claims.user_id)
        if user is None or user.github_id != claims.github_id:
            raise AuthenticationError("User session is no longer valid")
        return user
