"""Domain exceptions for Geospatial Harmonization Service."""


class DomainError(Exception):
    """Base exception for domain invariant and contract violations."""


class InvalidGridSpecError(DomainError):
    """Raised when a GridSpec definition is incomplete or internally inconsistent."""


class InvalidTemporalSpecError(DomainError):
    """Raised when a TemporalSpec violates ordering, timezone, or semantic rules."""


class IncompatibleDatasetError(DomainError):
    """Raised when a dataset lacks required spatial, temporal, or variable metadata."""


class QualityPolicyViolationError(DomainError):
    """Raised when quality constraints reject a dataset or requested operation."""
