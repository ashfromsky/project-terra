"""Integration tests for SqlAlchemyUserRepository and HttpxGitHubOAuthClient."""

import asyncio

import httpx
import pytest

from terra.config import Settings
from terra.infrastructure.database import DatabaseManager
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.auth.domain.exceptions import OAuthConfigurationError, OAuthExchangeError
from terra.modules.auth.infrastructure.github_client import HttpxGitHubOAuthClient
from terra.modules.auth.infrastructure.repositories.sqlalchemy import SqlAlchemyUserRepository


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        github_client_id="client-123",
        github_client_secret="secret-456",
    )


def test_sqlalchemy_user_repository_upsert_tracks_github_id_across_rename() -> None:
    async def scenario() -> None:
        db = DatabaseManager(_settings())
        await db.create_schema()
        try:
            async with db.session() as session:
                repo = SqlAlchemyUserRepository(session)
                created = await repo.upsert_by_github_id(
                    GitHubProfile(
                        github_id=777001,
                        github_login="initial-name",
                        display_name="Initial",
                        email="ada@terra.org",
                    )
                )
                fetched = await repo.get_by_github_id(777001)
                assert fetched is not None
                assert fetched.id == created.id

                updated = await repo.upsert_by_github_id(
                    GitHubProfile(
                        github_id=777001,
                        github_login="renamed-handle",
                        display_name="Ada",
                    )
                )
                assert updated.id == created.id
                assert updated.github_login == "renamed-handle"
                assert updated.email == "ada@terra.org"

                by_id = await repo.get_by_id(created.id)
                assert by_id is not None
                assert by_id.github_login == "renamed-handle"
        finally:
            await db.dispose()

    asyncio.run(scenario())


def test_httpx_github_client_exchanges_code_and_resolves_private_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_abc"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 987654, "login": "terra-dev", "email": None})
        if request.url.path == "/user/emails":
            return httpx.Response(
                200,
                json=[{"email": "dev@terra.org", "primary": True, "verified": True}],
            )
        return httpx.Response(404)

    async def scenario() -> None:
        client = HttpxGitHubOAuthClient(_settings(), transport=httpx.MockTransport(handler))
        profile = await client.exchange_code_for_profile("valid-code")
        assert profile.github_id == 987654
        assert profile.github_login == "terra-dev"
        assert profile.email == "dev@terra.org"

    asyncio.run(scenario())


def test_httpx_github_client_raises_on_rejected_code_or_missing_config() -> None:
    client = HttpxGitHubOAuthClient(
        Settings(_env_file=None, environment="test", github_client_id="", github_client_secret="")
    )
    with pytest.raises(OAuthConfigurationError):
        client.build_authorize_url("state")

    def reject_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    async def fail_exchange() -> None:
        configured = HttpxGitHubOAuthClient(
            _settings(),
            transport=httpx.MockTransport(reject_handler),
        )
        with pytest.raises(OAuthExchangeError):
            await configured.exchange_code_for_profile("bad-code")

    asyncio.run(fail_exchange())
