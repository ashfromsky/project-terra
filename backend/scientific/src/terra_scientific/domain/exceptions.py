"""Explicit domain exception hierarchy for Scientific Core."""

from collections.abc import Mapping


class ScientificCoreError(Exception):
    """Base error raised by deterministic scientific components."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "scientific_error",
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: dict[str, object] = dict(details) if details is not None else {}


class ScientificInputError(ScientificCoreError):
    """Raised when input data violates physical, provenance, or contract requirements."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_scientific_input",
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class UnsupportedSourceError(ScientificInputError):
    """Raised when an EO/meteorological product or version lacks a registered policy."""


class InsufficientDataError(ScientificCoreError):
    """Raised when valid sample size or temporal coverage fails minimum thresholds."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "insufficient_data",
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class TemporalAlignmentError(ScientificInputError):
    """Raised on conflicting temporal cadences, semantics, or timezone errors."""


class SpatialSupportError(ScientificInputError):
    """Raised on invalid CRS, footprint incompatibility, or mismatched spatial grids."""


class MethodConfigurationError(ScientificCoreError):
    """Raised when requested parameters contradict scientific validity constraints."""


class MethodUnavailableError(ScientificCoreError):
    """Raised when a deferred P2 or unvalidated method is invoked."""
