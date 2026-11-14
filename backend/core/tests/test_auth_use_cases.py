"""Unit tests for auth use cases and JWT token service."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from terra.config import Settings
from terra.modules.auth.application.use_cases import (
    AuthenticateGitHubCallbackUseCase,
    GetCurrentUserUseCase,
    StartGitHubLoginUseCase,
)
from terra.modules.auth.domain.entities import GitHubProfile, User
from terra.modules.auth.domain.exceptions import AuthenticationError
from terra.modules.auth.infrastructure.token_service import JwtTokenService


class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_github_id(self, github_id: int) -> User | None:
        return next((u for u in self._users.values() if u.github_id == github_id), None)

    async def upsert_by_github_id(self, profile: GitHubProfile) -> User:
        now = datetime.now(UTC)
        existing = await self.get_by_github_id(profile.github_id)
        uid = existing.id if existing else uuid4()
        fallback_email = existing.email if existing else None
        user = User(
            id=uid,
            github_id=profile.github_id,
            github_login=profile.github_login,
            display_name=profile.display_name,
            avatar_url=profile.avatar_url,
            email=profile.email if profile.email is not None else fallback_email,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._users[uid] = user
        return user


class FakeGitHubOAuthClient:
    def __init__(self, profile: GitHubProfile) -> None:
        self.profile = profile

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        return self.profile


def _auth_settings() -> Settings:
    return Settings(
        environment="test",
        github_client_id="client-123",
        github_client_secret="secret-456",
        jwt_secret_key="test-signing-key-with-sufficient-length",
    )


def test_github_login_and_username_change_keeps_same_user() -> None:
    async def scenario() -> None:
        tokens = JwtTokenService(_auth_settings())
        users = FakeUserRepository()
        gh = FakeGitHubOAuthClient(GitHubProfile(github_id=42001, github_login="old-handle"))

        url, state = StartGitHubLoginUseCase(gh, tokens).execute()
        assert state in url

        callback = AuthenticateGitHubCallbackUseCase(users, gh, tokens)
        first = await callback.execute(code="ok-1", state=state)
        assert first.user.github_id == 42001

        gh.profile = GitHubProfile(github_id=42001, github_login="new-handle", display_name="Ada")
        _, state2 = StartGitHubLoginUseCase(gh, tokens).execute()
        second = await callback.execute(code="ok-2", state=state2)
        assert second.user.id == first.user.id
        assert second.user.github_login == "new-handle"

        resolved = await GetCurrentUserUseCase(users, tokens).execute(second.access_token)
        assert resolved.id == first.user.id
        assert resolved.github_login == "new-handle"

    asyncio.run(scenario())


def test_oauth_state_cannot_be_used_as_access_token() -> None:
    tokens = JwtTokenService(_auth_settings())
    with pytest.raises(AuthenticationError):
        tokens.verify_access_token(tokens.issue_oauth_state())


def test_empty_code_is_rejected_before_exchange() -> None:
    async def scenario() -> None:
        tokens = JwtTokenService(_auth_settings())
        users = FakeUserRepository()
        gh = FakeGitHubOAuthClient(GitHubProfile(github_id=1, github_login="u"))
        _, state = StartGitHubLoginUseCase(gh, tokens).execute()
        with pytest.raises(AuthenticationError):
            await AuthenticateGitHubCallbackUseCase(users, gh, tokens).execute(" ", state)

    asyncio.run(scenario())
