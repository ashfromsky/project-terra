"""FastAPI dependency wiring for authentication and current-user resolution."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from terra.api.dependencies import DbSessionDep, SettingsDep
from terra.modules.auth.application.use_cases import GetCurrentUserUseCase
from terra.modules.auth.domain.entities import User
from terra.modules.auth.domain.exceptions import AuthenticationError
from terra.modules.auth.domain.ports import GitHubOAuthClient, TokenService
from terra.modules.auth.domain.repositories import UserRepository
from terra.modules.auth.infrastructure.github_client import HttpxGitHubOAuthClient
from terra.modules.auth.infrastructure.repositories.sqlalchemy import SqlAlchemyUserRepository
from terra.modules.auth.infrastructure.token_service import JwtTokenService


def get_user_repository(session: DbSessionDep) -> UserRepository:
    """Provide the SQLAlchemy-backed UserRepository."""
    return SqlAlchemyUserRepository(session)


def get_token_service(settings: SettingsDep) -> TokenService:
    """Provide the JWT TokenService."""
    return JwtTokenService(settings)


def get_github_oauth_client(settings: SettingsDep) -> GitHubOAuthClient:
    """Provide the GitHub OAuth HTTP client."""
    return HttpxGitHubOAuthClient(settings)


def _extract_token(request: Request, cookie_name: str) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    cookie_token = request.cookies.get(cookie_name)
    return cookie_token.strip() if cookie_token else None


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> User:
    """Resolve the currently authenticated user or fallback to researcher session."""
    token = _extract_token(request, settings.auth_cookie_name)
    if token:
        try:
            return await GetCurrentUserUseCase(users, tokens).execute(token)
        except AuthenticationError:
            pass

    if settings.auto_researcher_session:
        user = await users.get_by_github_id(123993174)
        if user is not None:
            return user
        from terra.modules.auth.domain.models import GitHubProfile

        return await users.upsert_by_github_id(
            GitHubProfile(
                github_id=123993174,
                github_login="ashfromsky",
                display_name="Timothy",
                avatar_url="https://avatars.githubusercontent.com/u/123993174?v=4",
                email="gamertimka9@gmail.com",
            )
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
GitHubOAuthClientDep = Annotated[GitHubOAuthClient, Depends(get_github_oauth_client)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
