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
