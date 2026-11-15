"""Temporal specification domain models preserving observation and composite semantics."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from geospatial_harmonization.domain.exceptions import DomainError, InvalidTemporalSpecError

TemporalSemantics = Literal["instantaneous", "interval", "composite", "climatology"]
TemporalAggregationKind = Literal[
    "none", "mean", "sum", "median", "min", "max", "rate_to_depth_sum", "quality_weighted_mean"
]


def require_tz_aware(
    dt: datetime, field_name: str, error_cls: type[DomainError] = InvalidTemporalSpecError
) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise error_cls(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TemporalSpec:
    """Explicit temporal support, cadence, and aggregation metadata."""

    start: datetime
    end: datetime
    cadence: str
    semantics: TemporalSemantics
    aggregation: TemporalAggregationKind = "none"
    composite_days: int | None = None
    acquisition_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        require_tz_aware(self.start, "start")
        require_tz_aware(self.end, "end")
        if self.acquisition_timestamp is not None:
            require_tz_aware(self.acquisition_timestamp, "acquisition_timestamp")
        if not self.cadence.strip():
            raise InvalidTemporalSpecError("cadence must be a non-empty string")
        if self.semantics == "instantaneous":
            if self.start != self.end:
                raise InvalidTemporalSpecError("instantaneous observations require start == end")
        elif self.start >= self.end:
            raise InvalidTemporalSpecError(f"{self.semantics} support requires start < end")
        if self.semantics == "composite":
            if self.composite_days is None or self.composite_days <= 0:
                raise InvalidTemporalSpecError("composite semantics require composite_days > 0")
        elif self.composite_days is not None:
            raise InvalidTemporalSpecError("composite_days requires semantics == 'composite'")

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()
