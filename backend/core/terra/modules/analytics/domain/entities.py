"""Domain entities and value objects for zonal statistics and time series."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ZonalHistogram:
    bins: list[float] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ZonalStatistics:
    metric_id: str
    date: str
    dataset_id: str
    mean: float | None
    median: float | None
    min: float | None
    max: float | None
    std: float | None
    q10: float | None
    q25: float | None
    q75: float | None
    q90: float | None
    valid_pixel_count: int
    total_pixel_count: int
    valid_data_coverage: float
    approx_area_km2: float
    units: str | None
    histogram: ZonalHistogram


@dataclass(frozen=True, slots=True)
class ZonalTimeseriesPoint:
    date: str
    mean: float | None
    median: float | None
    min: float | None
    max: float | None
    q25: float | None
    q75: float | None
    valid_data_coverage: float


@dataclass(frozen=True, slots=True)
class ZonalTimeseries:
    metric_id: str
    units: str | None
    series: list[ZonalTimeseriesPoint] = field(default_factory=list)
