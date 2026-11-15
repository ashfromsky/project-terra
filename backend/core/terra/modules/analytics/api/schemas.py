"""Request and response schemas for analytics and zonal statistics."""

from typing import Any
from uuid import UUID

from pydantic import Field

from terra.api.schemas import CamelModel
from terra.modules.analytics.domain.entities import (
    ZonalHistogram,
    ZonalStatistics,
    ZonalTimeseries,
    ZonalTimeseriesPoint,
)


class ZonalHistogramResponse(CamelModel):
    bins: list[float]
    counts: list[int]

    @classmethod
    def from_domain(cls, h: ZonalHistogram) -> "ZonalHistogramResponse":
        return cls(bins=h.bins, counts=h.counts)


class ZonalStatisticsRequest(CamelModel):
    metric_id: str = Field(alias="metricId")
    date: str | None = None
    geometry: dict[str, Any] | None = None
    region_id: UUID | None = Field(default=None, alias="regionId")


class ZonalStatisticsResponse(CamelModel):
    metric_id: str
    date: str
    dataset_id: str
    mean: float | None = None
    median: float | None = None
    min: float | None = None
    max: float | None = None
    std: float | None = None
    q10: float | None = None
    q25: float | None = None
    q75: float | None = None
    q90: float | None = None
    valid_pixel_count: int
    total_pixel_count: int
    valid_data_coverage: float
    approx_area_km2: float
    units: str | None = None
    histogram: ZonalHistogramResponse

    @classmethod
    def from_domain(cls, stats: ZonalStatistics) -> "ZonalStatisticsResponse":
        return cls(
            metric_id=stats.metric_id,
            date=stats.date,
            dataset_id=stats.dataset_id,
            mean=stats.mean,
            median=stats.median,
            min=stats.min,
            max=stats.max,
            std=stats.std,
            q10=stats.q10,
            q25=stats.q25,
            q75=stats.q75,
            q90=stats.q90,
            valid_pixel_count=stats.valid_pixel_count,
            total_pixel_count=stats.total_pixel_count,
            valid_data_coverage=stats.valid_data_coverage,
            approx_area_km2=stats.approx_area_km2,
            units=stats.units,
            histogram=ZonalHistogramResponse.from_domain(stats.histogram),
        )


class ZonalTimeseriesPointResponse(CamelModel):
    date: str
    mean: float | None = None
    median: float | None = None
    min: float | None = None
    max: float | None = None
    q25: float | None = None
    q75: float | None = None
    valid_data_coverage: float

    @classmethod
    def from_domain(cls, pt: ZonalTimeseriesPoint) -> "ZonalTimeseriesPointResponse":
        return cls(
            date=pt.date,
            mean=pt.mean,
            median=pt.median,
            min=pt.min,
            max=pt.max,
            q25=pt.q25,
            q75=pt.q75,
            valid_data_coverage=pt.valid_data_coverage,
        )


class ZonalTimeseriesRequest(CamelModel):
    metric_id: str = Field(alias="metricId")
    geometry: dict[str, Any] | None = None
    region_id: UUID | None = Field(default=None, alias="regionId")
    start_date: str | None = Field(default=None, alias="startDate")
    end_date: str | None = Field(default=None, alias="endDate")


class ZonalTimeseriesResponse(CamelModel):
    metric_id: str
    units: str | None = None
    series: list[ZonalTimeseriesPointResponse]

    @classmethod
    def from_domain(cls, ts: ZonalTimeseries) -> "ZonalTimeseriesResponse":
        return cls(
            metric_id=ts.metric_id,
            units=ts.units,
            series=[ZonalTimeseriesPointResponse.from_domain(pt) for pt in ts.series],
        )
