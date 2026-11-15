"""Domain exceptions for Geospatial Harmonization Service."""

import errno
import os
from typing import Literal

ErrorCategory = Literal[
    "authentication",
    "authorization",
    "validation",
    "network",
    "provider",
    "provider_disabled",
    "processing",
    "storage",
    "cancelled",
    "unknown",
]


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


class ProviderIngestionError(IncompatibleDatasetError):
    """Classified upstream provider or transport error carrying retryability semantics."""

    error_category: ErrorCategory = "provider"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        error_category: ErrorCategory | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        if error_category is not None:
            self.error_category = error_category
        if retryable is not None:
            self.retryable = retryable
        self.status_code = status_code
        self.provider = provider


class ProviderDisabledError(ProviderIngestionError):
    """Raised when a configured data provider is disabled by runtime settings."""

    error_category: ErrorCategory = "provider_disabled"
    retryable: bool = False


class ProviderAuthenticationError(ProviderIngestionError):
    """Raised on missing credentials, HTTP 401, or failed Earthdata URS login."""

    error_category: ErrorCategory = "authentication"
    retryable: bool = False


class ProviderAuthorizationError(ProviderIngestionError):
    """Raised on HTTP 403 or unapproved Earthdata application / EULA access."""

    error_category: ErrorCategory = "authorization"
    retryable: bool = False


class ProviderValidationError(ProviderIngestionError):
    """Raised on invalid queries, HTTP 400/404/422, or missing upstream granules."""

    error_category: ErrorCategory = "validation"
    retryable: bool = False


class TransientTransferError(ProviderIngestionError):
    """Raised on transient HTTP 429/5xx or network timeout/transport failures."""

    error_category: ErrorCategory = "network"
    retryable: bool = True


class ProviderResponseError(ProviderIngestionError):
    """Raised when an upstream response body violates expected content or structure."""

    error_category: ErrorCategory = "provider"
    retryable: bool = False


def classify_exception(exc: Exception) -> tuple[ErrorCategory, bool]:
    """Map an arbitrary exception to an explicit failure category and retryability flag."""
    if isinstance(exc, ProviderIngestionError):
        return exc.error_category, exc.retryable
    if isinstance(exc, (StorageError, ScratchCapacityError)):
        return "storage", False
    if isinstance(exc, OSError):
        # EDQUOT/ENOSPC (quota/no-space) are deterministic: retrying the same
        # materialization against the same constrained volume repeats the failure.
        if exc.errno in _SCRATCH_CAPACITY_ERRNOS:
            return "storage", False
        return "unknown", True
    if isinstance(
        exc,
        (
            InvalidGridSpecError,
            InvalidTemporalSpecError,
            QualityPolicyViolationError,
            IncompatibleDatasetError,
            ValueError,
        ),
    ):
        return "validation", False
    return "unknown", True


class StorageError(DomainError):
    """Base exception for storage zone, quota, lifecycle, and integrity violations."""


class StorageQuotaError(StorageError):
    """Base exception for storage quota and reservation enforcement errors."""


class StorageBudgetExceededError(StorageQuotaError):
    """Raised when an operation would exceed the configured storage budget."""

    def __init__(
        self,
        message: str,
        *,
        requested_bytes: int,
        available_bytes: int,
        budget_bytes: int,
        reserved_bytes: int = 0,
        zone: str | None = None,
        code: str = "STORAGE_BUDGET_EXCEEDED",
    ) -> None:
        super().__init__(message)
        self.requested_bytes = requested_bytes
        self.available_bytes = available_bytes
        self.budget_bytes = budget_bytes
        self.reserved_bytes = reserved_bytes
        self.zone = zone
        self.code = code


class ObjectTooLargeError(StorageQuotaError):
    """Raised when an object, job output, or temporary allocation exceeds configured caps."""

    def __init__(
        self,
        message: str,
        *,
        requested_bytes: int,
        limit_bytes: int,
        scope: str,
        code: str = "OBJECT_TOO_LARGE",
    ) -> None:
        super().__init__(message)
        self.requested_bytes = requested_bytes
        self.limit_bytes = limit_bytes
        self.scope = scope
        self.code = code


class StorageImmutabilityError(StorageError):
    """Raised when attempting to overwrite or auto-delete an immutable storage asset."""


class StorageIntegrityError(StorageError):
    """Raised on checksum mismatch, missing referenced asset, or unsafe precision loss."""


class StorageReservationError(StorageQuotaError):
    """Raised on invalid reservation lookup, expiration, or state transition."""


class ScratchCapacityError(StorageError):
    """Raised when a scratch write hits a disk-quota (EDQUOT) or no-space (ENOSPC) condition.

    Deliberately non-retryable: retrying the same materialization against the
    same constrained scratch volume would repeat the identical disk failure.
    """

    error_category: ErrorCategory = "storage"
    retryable: bool = False
    code: str = "SCRATCH_CAPACITY_EXCEEDED"

    def __init__(
        self,
        message: str,
        *,
        requested_bytes: int | None = None,
        available_bytes: int | None = None,
        os_errno: int | None = None,
    ) -> None:
        super().__init__(message)
        self.requested_bytes = requested_bytes
        self.available_bytes = available_bytes
        self.os_errno = os_errno


_SCRATCH_CAPACITY_ERRNOS = frozenset({errno.EDQUOT, errno.ENOSPC})


def scratch_capacity_error_from_oserror(exc: OSError) -> ScratchCapacityError | None:
    """Translate EDQUOT/ENOSPC OSErrors into :class:`ScratchCapacityError`, else None."""
    if exc.errno not in _SCRATCH_CAPACITY_ERRNOS:
        return None
    errno_name = os.strerror(exc.errno) if exc.errno is not None else str(exc.errno)
    return ScratchCapacityError(
        f"Scratch storage write failed ({errno_name}): {exc}",
        os_errno=exc.errno,
    )
