"""Auth domain exceptions independent of HTTP transport."""


class AuthDomainError(Exception):
    """Base exception for authentication failures."""


class AuthenticationError(AuthDomainError):
    """Raised when credentials, state, or session tokens are invalid."""


class OAuthConfigurationError(AuthDomainError):
    """Raised when GitHub OAuth client settings are missing."""


class OAuthExchangeError(AuthDomainError):
    """Raised when GitHub OAuth token exchange or user lookup fails."""
