"""Domain exceptions for analytics module."""


class AnalyticsDomainError(Exception):
    """Base domain exception for analytics."""


class MetricNotFoundError(AnalyticsDomainError):
    """Raised when an environmental metric or layer cannot be found."""


class DatasetUnavailableError(AnalyticsDomainError):
    """Raised when no raster dataset is available for the metric/date."""


class ZonalCalculationError(AnalyticsDomainError):
    """Raised when computing zonal statistics fails upstream."""
