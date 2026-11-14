"""JWT-backed implementation of the TokenService port."""

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

import jwt

from terra.config import Settings
from terra.modules.auth.domain.entities import AccessTokenClaims, User
from terra.modules.auth.domain.exceptions import AuthenticationError

_OAUTH_STATE_TTL = timedelta(minutes=10)


class JwtTokenService:
    """Issues and verifies signed OAuth state tokens and session JWTs."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._access_ttl = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    def issue_oauth_state(self) -> str:
        """Create a short-lived signed state token for CSRF protection."""
        now = datetime.now(UTC)
        payload = {
            "type": "oauth_state",
            "jti": token_urlsafe(16),
            "iat": now,
            "exp": now + _OAUTH_STATE_TTL,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_oauth_state(self, state: str) -> None:
        """Verify OAuth state signature, expiry, and token type."""
        payload = self._decode(state, expected_type="oauth_state")
        if not payload.get("jti"):
            raise AuthenticationError("Invalid OAuth state")

    def issue_access_token(self, user: User) -> str:
        """Create a signed JWT access token bound to internal and GitHub IDs."""
        now = datetime.now(UTC)
        payload = {
            "type": "access",
            "sub": str(user.id),
            "github_id": user.github_id,
            "iat": now,
            "exp": now + self._access_ttl,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        """Decode and validate a session JWT into AccessTokenClaims."""
        payload = self._decode(token, expected_type="access")
        sub = payload.get("sub")
        github_id = payload.get("github_id")
        if (
            not isinstance(sub, str)
            or not isinstance(github_id, int)
            or isinstance(github_id, bool)
        ):
            raise AuthenticationError("Invalid access token claims")
        try:
            user_id = UUID(sub)
        except ValueError as exc:
            raise AuthenticationError("Invalid access token subject") from exc
        return AccessTokenClaims(user_id=user_id, github_id=github_id)

    def _decode(self, token: str, expected_type: str) -> dict[str, object]:
        if not token:
            raise AuthenticationError("Missing token")
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc
        if payload.get("type") != expected_type:
            raise AuthenticationError("Unexpected token type")
        return payload
