"""HTTP client for GitHub OAuth code exchange and user profile retrieval."""

from urllib.parse import urlencode

import httpx

from terra.config import Settings
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.auth.domain.exceptions import OAuthConfigurationError, OAuthExchangeError

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"
_TIMEOUT_SECONDS = 10.0


class HttpxGitHubOAuthClient:
    """Async httpx adapter implementing GitHubOAuthClient."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = settings.github_client_id
        self._client_secret = settings.github_client_secret.get_secret_value()
        self._redirect_uri = settings.github_redirect_uri
        self._scopes = settings.github_oauth_scopes
        self._transport = transport

    def _require_configured(self) -> None:
        if not self._client_id or not self._client_secret:
            raise OAuthConfigurationError("GitHub OAuth credentials are not configured")

    def build_authorize_url(self, state: str) -> str:
        """Construct the GitHub OAuth authorization redirect URL."""
        self._require_configured()
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": self._scopes,
                "state": state,
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def exchange_code_for_profile(self, code: str) -> GitHubProfile:
        """Exchange authorization code for a token and fetch the GitHub profile."""
        self._require_configured()
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            transport=self._transport,
        ) as client:
            access_token = await self._fetch_access_token(client, code)
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "TERRA-Core-API",
            }
            user_data = await self._fetch_user(client, headers)
            email = user_data.get("email")
            if not isinstance(email, str) or not email:
                email = await self._fetch_primary_email(client, headers)

        github_id = user_data.get("id")
        github_login = user_data.get("login")
        if (
            not isinstance(github_id, int)
            or isinstance(github_id, bool)
            or not isinstance(github_login, str)
        ):
            raise OAuthExchangeError("GitHub profile response missing required identity fields")

        name = user_data.get("name")
        avatar = user_data.get("avatar_url")
        return GitHubProfile(
            github_id=github_id,
            github_login=github_login,
            display_name=name if isinstance(name, str) else None,
            avatar_url=avatar if isinstance(avatar, str) else None,
            email=email if isinstance(email, str) else None,
        )

    async def _fetch_access_token(self, client: httpx.AsyncClient, code: str) -> str:
        try:
            response = await client.post(
                _TOKEN_URL,
                headers={"Accept": "application/json", "User-Agent": "TERRA-Core-API"},
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthExchangeError("Failed to exchange GitHub authorization code") from exc

        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise OAuthExchangeError("GitHub rejected authorization code")
        return token

    async def _fetch_user(self, client: httpx.AsyncClient, headers: dict[str, str]) -> dict:
        try:
            response = await client.get(_USER_URL, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthExchangeError("Failed to fetch GitHub user profile") from exc
        if not isinstance(payload, dict):
            raise OAuthExchangeError("Unexpected GitHub user profile format")
        return payload

    async def _fetch_primary_email(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
    ) -> str | None:
        try:
            response = await client.get(_EMAILS_URL, headers=headers)
            if response.status_code != 200:
                return None
            emails = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(emails, list):
            return None
        for entry in emails:
            if (
                isinstance(entry, dict)
                and entry.get("primary") is True
                and entry.get("verified") is True
                and isinstance(entry.get("email"), str)
            ):
                return entry["email"]
        return None
