"""Domain exceptions for geographic regions."""


class RegionDomainError(Exception):
    """Base error for region domain rule violations."""


class InvalidGeometryError(RegionDomainError):
    """Raised when an AOI GeoJSON geometry fails WGS 84 structural validation."""


class RegionNotFoundError(RegionDomainError):
    """Raised when a requested region does not exist."""


class RegionAccessDeniedError(RegionDomainError):
    """Raised when a user accesses a region owned by another user."""
