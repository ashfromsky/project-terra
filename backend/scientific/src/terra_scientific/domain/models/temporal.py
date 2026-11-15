"""Temporal contracts and timezone-aware interval validation."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from terra_scientific.domain.enums import TemporalCadence, TemporalSemantics

SECONDS_PER_DAY = 86400.0
JULIAN_YEAR_DAYS = 365.25


def ensure_utc(value: datetime) -> datetime:
    """Validate that ``value`` is timezone-aware and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Timestamp must be timezone-aware, got {value!r}")
    return value.astimezone(UTC)


class TimeInterval(BaseModel):
    """Closed or half-open UTC observation interval."""

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime
    is_closed: bool = True

    @model_validator(mode="after")
    def _validate_order(self) -> "TimeInterval":
        object.__setattr__(self, "start", ensure_utc(self.start))
        object.__setattr__(self, "end", ensure_utc(self.end))
        if self.end < self.start:
            raise ValueError(
                f"Interval end ({self.end.isoformat()}) precedes start ({self.start.isoformat()})"
            )
        return self

    @property
    def elapsed_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0

    @property
    def elapsed_days(self) -> float:
        return (self.end - self.start).total_seconds() / SECONDS_PER_DAY

    @property
    def elapsed_years(self) -> float:
        return self.elapsed_days / JULIAN_YEAR_DAYS


class TemporalMetadata(BaseModel):
    """Temporal cadence and interval coverage metadata for a dataset."""

    model_config = ConfigDict(frozen=True)

    cadence: TemporalCadence
    semantics: TemporalSemantics
    start: datetime
    end: datetime
    composite_days: int | None = Field(default=None, ge=1)
    expected_interval_count: int | None = Field(default=None, ge=0)
    calendar: str = "gregorian"
    time_zone: str = "UTC"

    @model_validator(mode="after")
    def _validate_bounds(self) -> "TemporalMetadata":
        object.__setattr__(self, "start", ensure_utc(self.start))
        object.__setattr__(self, "end", ensure_utc(self.end))
        if self.end < self.start:
            raise ValueError("TemporalMetadata.end must be >= start")
        if self.semantics == TemporalSemantics.COMPOSITE and self.composite_days is None:
            raise ValueError("Composite temporal semantics require composite_days")
        return self
