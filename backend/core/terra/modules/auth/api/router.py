"""GitHub OAuth and session endpoints under ``/api/v1/auth``."""

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse

from terra.api.dependencies import SettingsDep
from terra.modules.auth.api.dependencies import (
    CurrentUserDep,
    GitHubOAuthClientDep,
    TokenServiceDep,
    UserRepositoryDep,
)
from terra.modules.auth.api.schemas import (
    AuthCallbackResponse,
    GitHubLoginResponse,
    LogoutResponse,
    UserResponse,
)
from terra.modules.auth.application.use_cases import (
    AuthenticateGitHubCallbackUseCase,
    StartGitHubLoginUseCase,
)
from terra.modules.auth.domain.exceptions import (
    AuthenticationError,
    OAuthConfigurationError,
    OAuthExchangeError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/github/login", response_model=GitHubLoginResponse)
async def github_login(
    github_client: GitHubOAuthClientDep,
    token_service: TokenServiceDep,
    redirect: bool = Query(default=False),
) -> GitHubLoginResponse | RedirectResponse:
    """Initiate GitHub OAuth flow via JSON URL or HTTP redirect."""
    try:
        authorize_url, _ = StartGitHubLoginUseCase(github_client, token_service).execute()
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if redirect:
        return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    return GitHubLoginResponse(authorize_url=authorize_url)


@router.get("/github/callback", response_model=AuthCallbackResponse)
async def github_callback(
    response: Response,
    settings: SettingsDep,
    users: UserRepositoryDep,
    github_client: GitHubOAuthClientDep,
    token_service: TokenServiceDep,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    redirect: bool = Query(default=False),
) -> AuthCallbackResponse | RedirectResponse:
    """Handle GitHub OAuth callback, upsert user by GitHub ID, and issue session."""
    use_case = AuthenticateGitHubCallbackUseCase(users, github_client, token_service)
    try:
        session = await use_case.execute(code=code, state=state)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    cookie_kwargs = {
        "key": settings.auth_cookie_name,
        "value": session.access_token,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.auth_cookie_secure,
        "max_age": settings.jwt_access_token_expire_minutes * 60,
        "path": "/",
    }
    if redirect:
        redirect_resp = RedirectResponse(
            url=settings.frontend_auth_redirect_url,
            status_code=status.HTTP_302_FOUND,
        )
        redirect_resp.set_cookie(**cookie_kwargs)
        return redirect_resp

    response.set_cookie(**cookie_kwargs)
    return AuthCallbackResponse(
        access_token=session.access_token,
        user=UserResponse.from_domain(session.user),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(response: Response, settings: SettingsDep) -> LogoutResponse:
    """Clear the HttpOnly authentication session cookie."""
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse.from_domain(current_user)
