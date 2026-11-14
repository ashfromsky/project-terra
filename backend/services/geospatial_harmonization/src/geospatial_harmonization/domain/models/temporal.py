"""Temporal specification domain models preserving observation and composite semantics."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from geospatial_harmonization.domain.exceptions import InvalidTemporalSpecError

TemporalSemantics = Literal["instantaneous", "interval", "composite", "climatology"]
TemporalAggregationKind = Literal[
    "none", "mean", "sum", "median", "min", "max", "rate_to_depth_sum", "quality_weighted_mean"
]


def _require_tz_aware(dt: datetime, field_name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise InvalidTemporalSpecError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TemporalSpec:
    """Explicit temporal support, cadence, and aggregation metadata."""

    start: datetime
    end: datetime
    cadence: str
    semantics: TemporalSemantics
    aggregation: TemporalAggregationKind = "none"
    composite_days: int | None = None

    def __post_init__(self) -> None:
        _require_tz_aware(self.start, "start")
        _require_tz_aware(self.end, "end")
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
