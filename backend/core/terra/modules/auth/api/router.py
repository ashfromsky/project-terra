"""GitHub OAuth and session endpoints under ``/api/v1/auth``."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from terra.api.dependencies import SettingsDep
from terra.config import Settings
from terra.modules.auth.api.dependencies import (
    GitHubOAuthClientDep,
    TokenServiceDep,
    UserRepositoryDep,
    _extract_token,
)
from terra.modules.auth.api.schemas import (
    AuthCallbackResponse,
    GitHubLoginResponse,
    LogoutResponse,
    UserResponse,
)
from terra.modules.auth.application.use_cases import (
    AuthenticateGitHubCallbackUseCase,
    GetCurrentUserUseCase,
    StartGitHubLoginUseCase,
)
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.auth.domain.exceptions import (
    AuthenticationError,
    OAuthConfigurationError,
    OAuthExchangeError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _resolve_frontend_base_url(
    request: Request,
    settings: Settings,
    fallback: str,
) -> str:
    """Resolve the frontend redirect base origin from reverse-proxy headers or fallback."""
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    if forwarded_host:
        candidate = f"{forwarded_proto}://{forwarded_host}"
        for allowed in settings.cors_origins:
            if candidate.lower() == allowed.lower():
                return candidate
    return fallback


def _build_frontend_redirect_url(
    base_url: str,
    return_to: str | None = None,
    *,
    auth_error: str | None = None,
    fragment: str | None = None,
) -> str:
    parsed = urlsplit(base_url)
    target_path = parsed.path
    target_query = parsed.query
    if return_to:
        rel = urlsplit(return_to)
        if rel.path:
            target_path = rel.path
        target_query = rel.query
    query_params = dict(parse_qsl(target_query, keep_blank_values=True))
    if auth_error:
        query_params["authError"] = auth_error
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            target_path,
            urlencode(query_params),
            fragment or "",
        )
    )


@router.get("/github/login", response_model=GitHubLoginResponse)
@router.post("/github/login", response_model=GitHubLoginResponse, include_in_schema=False)
async def github_login(
    github_client: GitHubOAuthClientDep,
    token_service: TokenServiceDep,
    redirect: bool = Query(default=False),
    return_to: str | None = Query(default=None, alias="returnTo"),
) -> GitHubLoginResponse | RedirectResponse:
    """Initiate GitHub OAuth flow via JSON URL or HTTP redirect."""
    try:
        authorize_url, _ = StartGitHubLoginUseCase(github_client, token_service).execute(
            redirect_to_frontend=redirect,
            return_to=return_to,
        )
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if redirect:
        return RedirectResponse(url=authorize_url, status_code=status.HTTP_302_FOUND)
    return GitHubLoginResponse(authorize_url=authorize_url)


@router.get("/github/callback", response_model=AuthCallbackResponse)
@router.post("/github/callback", response_model=AuthCallbackResponse, include_in_schema=False)
async def github_callback(
    request: Request,
    response: Response,
    settings: SettingsDep,
    users: UserRepositoryDep,
    github_client: GitHubOAuthClientDep,
    token_service: TokenServiceDep,
    state: str | None = Query(default=None),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    redirect: bool = Query(default=False),
) -> AuthCallbackResponse | RedirectResponse:
    """Handle GitHub OAuth callback, upsert user by GitHub ID, and issue session."""
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    state = state or body.get("state")
                    code = code or body.get("code")
                    error = error or body.get("error")
                    if "redirect" in body:
                        redirect = bool(body["redirect"])
            except Exception:
                pass
        elif "form" in content_type:
            try:
                form = await request.form()
                state = state or form.get("state")
                code = code or form.get("code")
                error = error or form.get("error")
                if "redirect" in form:
                    redirect = form.get("redirect") == "true"
            except Exception:
                pass

    if state is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Missing GitHub OAuth state parameter",
        )
    if error is not None:
        try:
            claims = token_service.verify_oauth_state(state)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        frontend_base = _resolve_frontend_base_url(
            request,
            settings,
            fallback=settings.frontend_auth_redirect_url,
        )
        if redirect or claims.redirect_to_frontend:
            return RedirectResponse(
                url=_build_frontend_redirect_url(
                    frontend_base,
                    claims.return_to,
                    auth_error=error,
                ),
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"GitHub OAuth error: {error}",
        )

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Missing GitHub authorization code",
        )

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
        try:
            claims = token_service.verify_oauth_state(state)
        except AuthenticationError:
            claims = None
        frontend_base = _resolve_frontend_base_url(
            request,
            settings,
            fallback=settings.frontend_auth_redirect_url,
        )
        if claims is not None and (redirect or claims.redirect_to_frontend):
            return RedirectResponse(
                url=_build_frontend_redirect_url(
                    frontend_base,
                    claims.return_to,
                    auth_error="oauth_exchange_failed",
                ),
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    samesite_val = "none" if settings.auth_cookie_secure else "lax"
    cookie_kwargs = {
        "key": settings.auth_cookie_name,
        "value": session.access_token,
        "httponly": True,
        "samesite": samesite_val,
        "secure": settings.auth_cookie_secure,
        "max_age": settings.jwt_access_token_expire_minutes * 60,
        "path": "/",
    }
    if redirect or session.redirect_to_frontend:
        frontend_base = _resolve_frontend_base_url(
            request,
            settings,
            fallback=settings.frontend_auth_redirect_url,
        )
        redirect_resp = RedirectResponse(
            url=_build_frontend_redirect_url(
                frontend_base,
                session.return_to,
            ),
            status_code=status.HTTP_302_FOUND,
        )
        redirect_resp.set_cookie(**cookie_kwargs)
        redirect_resp.delete_cookie(key="terra_logged_out", path="/")
        return redirect_resp

    response.set_cookie(**cookie_kwargs)
    response.delete_cookie(key="terra_logged_out", path="/")
    return AuthCallbackResponse(
        access_token=session.access_token,
        user=UserResponse.from_domain(session.user),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(response: Response, settings: SettingsDep) -> LogoutResponse:
    """Clear the HttpOnly authentication session cookie."""
    samesite_val = "none" if settings.auth_cookie_secure else "lax"
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        samesite=samesite_val,
        secure=settings.auth_cookie_secure,
    )
    response.delete_cookie(key="terra_logged_out", path="/")
    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    response: Response,
    settings: SettingsDep,
    users: UserRepositoryDep,
    token_service: TokenServiceDep,
) -> UserResponse:
    """Return the currently authenticated profile or auto-provision a researcher session."""
    token = _extract_token(request, settings.auth_cookie_name)
    if token:
        try:
            user = await GetCurrentUserUseCase(users, token_service).execute(token)
            return UserResponse.from_domain(user)
        except AuthenticationError:
            pass

    if settings.auto_researcher_session:
        user = await users.get_by_github_id(123993174)
        if user is None:
            user = await users.upsert_by_github_id(
                GitHubProfile(
                    github_id=123993174,
                    github_login="ashfromsky",
                    display_name="Timothy",
                    avatar_url="https://avatars.githubusercontent.com/u/123993174?v=4",
                    email="gamertimka9@gmail.com",
                )
            )

        session_token = token_service.issue_access_token(user)
        samesite_val = "none" if settings.auth_cookie_secure else "lax"
        cookie_kwargs = {
            "key": settings.auth_cookie_name,
            "value": session_token,
            "httponly": True,
            "samesite": samesite_val,
            "secure": settings.auth_cookie_secure,
            "max_age": settings.jwt_access_token_expire_minutes * 60,
            "path": "/",
        }
        response.set_cookie(**cookie_kwargs)
        response.delete_cookie(key="terra_logged_out", path="/")
        return UserResponse.from_domain(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/dev-session", response_model=AuthCallbackResponse)
async def dev_session(
    response: Response,
    settings: SettingsDep,
    users: UserRepositoryDep,
    token_service: TokenServiceDep,
) -> AuthCallbackResponse:
    """Issue a local researcher session cookie and bearer token in development mode."""
    if settings.environment != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development session login is only enabled in development environment",
        )

    user = await users.upsert_by_github_id(
        GitHubProfile(
            github_id=9990001,
            github_login="terra-dev-researcher",
            display_name="TERRA Local Researcher",
            avatar_url=None,
            email="researcher@terra.local",
        )
    )
    access_token = token_service.issue_access_token(user)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )
    response.delete_cookie(key="terra_logged_out", path="/")
    return AuthCallbackResponse(
        access_token=access_token,
        user=UserResponse.from_domain(user),
    )
