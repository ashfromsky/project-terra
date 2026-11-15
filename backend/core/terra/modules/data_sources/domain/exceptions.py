"""Domain exceptions for Core data sources discovery and ingestion orchestration."""


class DataSourcesDomainError(Exception):
    """Base error for data sources domain and integration failures."""


class DataSourcesValidationError(DataSourcesDomainError):
    """Raised when discovery or ingestion request parameters are invalid."""


class DataSourcesNotFoundError(DataSourcesDomainError):
    """Raised when a referenced region, operation, or dataset does not exist."""


class DataSourcesAccessDeniedError(DataSourcesDomainError):
    """Raised when a user accesses a region or ingestion owned by another user."""


class DataSourcesGhsError(DataSourcesDomainError):
    """Raised when communication with Geospatial Harmonization Service fails."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code
