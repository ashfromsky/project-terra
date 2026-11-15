"""Domain exceptions for scientific assessment orchestration."""


class AssessmentDomainError(Exception):
    """Base error for assessment domain and validation failures."""


class AssessmentValidationError(AssessmentDomainError):
    """Raised when assessment request configuration or input datasets are invalid."""


class AssessmentNotFoundError(AssessmentDomainError):
    """Raised when an assessment record does not exist."""


class AssessmentAccessDeniedError(AssessmentDomainError):
    """Raised when a user accesses an assessment owned by another user."""


class AssessmentRegionNotFoundError(AssessmentDomainError):
    """Raised when a referenced region does not exist."""


class AssessmentRegionAccessDeniedError(AssessmentDomainError):
    """Raised when a user references a region owned by another user."""


class GhsIntegrationError(AssessmentDomainError):
    """Raised when fetching prepared dataset metadata from GHS fails."""
