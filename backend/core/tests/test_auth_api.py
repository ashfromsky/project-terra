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


def test_dev_session_enabled_only_in_development_and_sets_cookie() -> None:
    dev_app = create_app(
        Settings(
            _env_file=None,
            environment="development",
            database_url="sqlite+aiosqlite:///:memory:",
        )
    )
    with TestClient(dev_app) as dev_client:
        sys_info = dev_client.get("/api/v1/system/info")
        assert sys_info.status_code == 200
        assert sys_info.json()["devAuthEnabled"] is True

        resp = dev_client.post("/api/v1/auth/dev-session")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["user"]["githubLogin"] == "terra-dev-researcher"
        assert payload["accessToken"]

        me = dev_client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["githubLogin"] == "terra-dev-researcher"

    for blocked_env in ("test", "production"):
        extra = (
            {"jwt_secret_key": "production-secret-at-least-thirty-two-bytes-long"}
            if blocked_env == "production"
            else {}
        )
        blocked_app = create_app(
            Settings(
                _env_file=None,
                environment=blocked_env,
                database_url="sqlite+aiosqlite:///:memory:",
                **extra,
            )
        )
        with TestClient(blocked_app) as blocked_client:
            sys_info = blocked_client.get("/api/v1/system/info")
            assert sys_info.status_code == 200
            assert sys_info.json()["devAuthEnabled"] is False

            blocked_resp = blocked_client.post("/api/v1/auth/dev-session")
            assert blocked_resp.status_code == 403


def test_github_login_and_callback_support_post_method() -> None:
    stub = StubGitHubClient(GitHubProfile(github_id=888, github_login="post-user"))
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
        login_post = client.post(
            "/api/v1/auth/github/login",
            params={"redirect": "true", "returnTo": "/explore"},
            follow_redirects=False,
        )
        assert login_post.status_code == 302
        state = _extract_state(login_post.headers["location"])

        cb_post_json = client.post(
            "/api/v1/auth/github/callback",
            json={"code": "post-code", "state": state},
            params={"redirect": "true"},
            follow_redirects=False,
        )
        assert cb_post_json.status_code == 302
        assert "terra_session" in cb_post_json.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/auth/me").json()["githubLogin"] == "post-user"


def test_github_callback_preserves_forwarded_host_origin() -> None:
    stub = StubGitHubClient(GitHubProfile(github_id=999, github_login="forwarded-user"))
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
            frontend_auth_redirect_url="https://api-terra.yappin.studio/explore",
            cors_origins=["https://project-terra.pages.dev", "https://api-terra.yappin.studio"],
        )
    )
    app.dependency_overrides[get_github_oauth_client] = lambda: stub

    with TestClient(app) as client:
        login_resp = client.get(
            "/api/v1/auth/github/login",
            params={"redirect": "true", "returnTo": "/assessments"},
            follow_redirects=False,
        )
        state = _extract_state(login_resp.headers["location"])

        cb_resp = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "c", "state": state},
            headers={
                "X-Forwarded-Host": "project-terra.pages.dev",
                "X-Forwarded-Proto": "https",
            },
            follow_redirects=False,
        )
        assert cb_resp.status_code == 302
        # Redirect must stay on project-terra.pages.dev where cookie is accepted!
        assert cb_resp.headers["location"] == "https://project-terra.pages.dev/assessments"


def test_auto_researcher_session_when_enabled() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
            auto_researcher_session=True,
        )
    )

    with TestClient(app) as client:
        # Request without cookies auto-provisions researcher session
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["githubLogin"] == "ashfromsky"
        assert "terra_session" in resp.headers.get("set-cookie", "")

        # Even after logout or without any credentials, auto_researcher_session preserves access
        logout_resp = client.post("/api/v1/auth/logout")
        assert logout_resp.status_code == 200

        logged_out_me = client.get("/api/v1/auth/me")
        assert logged_out_me.status_code == 200
        assert logged_out_me.json()["githubLogin"] == "ashfromsky"

        # Endpoints requiring authentication resolve the auto-researcher user
        assessments_resp = client.get("/api/v1/assessments")
        assert assessments_resp.status_code == 200
        assert assessments_resp.json() == []


def test_auth_me_returns_401_when_auto_researcher_session_disabled() -> None:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+aiosqlite:///:memory:",
            github_client_id="cid",
            github_client_secret="csec",
            auto_researcher_session=False,
        )
    )

    with TestClient(app) as client:
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"

        assessments_resp = client.get("/api/v1/assessments")
        assert assessments_resp.status_code == 401
