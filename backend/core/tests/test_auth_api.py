"""API tests for GitHub OAuth flow, session cookie/bearer auth, and /me."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from terra.config import Settings
from terra.main import create_app
from terra.modules.auth.api.dependencies import get_github_oauth_client
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.auth.domain.exceptions import OAuthExchangeError


class StubGitHubClient:
    def __init__(self, profile: GitHubProfile) -> None:
        self.profile = profile
        self.fail_exchange = False

    def build_authorize_url(self, state: str) -> str:
        return f"https://github.com/login/oauth/authorize?client_id=gh&state={state}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        if self.fail_exchange:
            raise OAuthExchangeError("GitHub exchange failed")
        return self.profile


def _extract_state(authorize_url: str) -> str:
    return parse_qs(urlparse(authorize_url).query)["state"][0]


def test_github_login_requires_oauth_config(client: TestClient) -> None:
    response = client.get("/api/v1/auth/github/login")
    assert response.status_code == 503


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_full_github_oauth_flow_bearer_cookie_and_username_update() -> None:
    stub = StubGitHubClient(
        GitHubProfile(github_id=555123, github_login="old-user", display_name="User")
    )
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
        )
    )
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        login_resp = client.get("/api/v1/auth/github/login")
        assert login_resp.status_code == 200
        state = _extract_state(login_resp.json()["authorizeUrl"])

        cb_resp = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "gh-code", "state": state},
        )
        assert cb_resp.status_code == 200
        payload = cb_resp.json()
        token = payload["accessToken"]
        user_id = payload["user"]["id"]
        assert payload["user"]["githubId"] == 555123
        assert payload["user"]["githubLogin"] == "old-user"

        me_cookie = client.get("/api/v1/auth/me")
        assert me_cookie.status_code == 200
        assert me_cookie.json()["id"] == user_id

        # Rename GitHub username and log in again: same internal id, updated login.
        stub.profile = GitHubProfile(github_id=555123, github_login="new-user", display_name="New")
        state2 = _extract_state(client.get("/api/v1/auth/github/login").json()["authorizeUrl"])
        cb2 = client.get("/api/v1/auth/github/callback", params={"code": "c2", "state": state2})
        assert cb2.status_code == 200
        assert cb2.json()["user"]["id"] == user_id
        assert cb2.json()["user"]["githubLogin"] == "new-user"

        logout_resp = client.post("/api/v1/auth/logout")
        assert logout_resp.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401

        me_bearer = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_bearer.status_code == 200
        assert me_bearer.json()["githubLogin"] == "new-user"


def test_callback_rejects_invalid_state_and_handles_exchange_error() -> None:
    stub = StubGitHubClient(GitHubProfile(github_id=1, github_login="u"))
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        bad_state = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "c", "state": "tampered"},
        )
        assert bad_state.status_code == 401

        state = _extract_state(client.get("/api/v1/auth/github/login").json()["authorizeUrl"])
        stub.fail_exchange = True
        failed = client.get("/api/v1/auth/github/callback", params={"code": "c", "state": state})
        assert failed.status_code == 502


def test_github_login_redirect_roundtrip_and_safe_return_to() -> None:
    stub = StubGitHubClient(GitHubProfile(github_id=777, github_login="gh-user"))
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
            frontend_auth_redirect_url="http://localhost:5173",
        )
    )
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        login_resp = client.get(
            "/api/v1/auth/github/login",
            params={"redirect": "true", "returnTo": "/explore?proj=globe"},
            follow_redirects=False,
        )
        assert login_resp.status_code == 302
        state = _extract_state(login_resp.headers["location"])

        cb_resp = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "gh-code", "state": state},
            follow_redirects=False,
        )
        assert cb_resp.status_code == 302
        assert cb_resp.headers["location"] == "http://localhost:5173/explore?proj=globe"
        assert client.get("/api/v1/auth/me").status_code == 200

        bad_return_login = client.get(
            "/api/v1/auth/github/login",
            params={"redirect": "true", "returnTo": "https://evil.example/steal"},
            follow_redirects=False,
        )
        bad_state = _extract_state(bad_return_login.headers["location"])
        denied_resp = client.get(
            "/api/v1/auth/github/callback",
            params={"error": "access_denied", "state": bad_state},
            follow_redirects=False,
        )
        assert denied_resp.status_code == 302
        assert denied_resp.headers["location"] == "http://localhost:5173?authError=access_denied"
