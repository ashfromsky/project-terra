"""Analytics REST API endpoints under ``/api/v1/analytics``."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from terra.api.dependencies import DbSessionDep
from terra.config import get_settings
from terra.modules.analytics.api.schemas import (
    ZonalStatisticsRequest,
    ZonalStatisticsResponse,
    ZonalTimeseriesRequest,
    ZonalTimeseriesResponse,
)
from terra.modules.analytics.application.services import AnalyticsService
from terra.modules.analytics.domain.exceptions import (
    DatasetUnavailableError,
    MetricNotFoundError,
    ZonalCalculationError,
)
from terra.modules.layers.api.router import get_layer_service
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_analytics_service(session: DbSessionDep) -> AnalyticsService:
    """Provide AnalyticsService wired with LayerCatalogService and RegionRepository."""
    settings = get_settings()
    layer_service = get_layer_service()
    region_repo = SqlAlchemyRegionRepository(session)
    return AnalyticsService(
        layer_service,
        ghs_base_url=settings.ghs_base_url,
        ghs_timeout_seconds=settings.ghs_timeout_seconds,
        region_repo=region_repo,
    )


AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]


@router.post("/zonal-statistics", response_model=ZonalStatisticsResponse)
async def compute_zonal_statistics(
    body: ZonalStatisticsRequest,
    service: AnalyticsServiceDep,
) -> ZonalStatisticsResponse:
    """Compute physical raster zonal statistics within a GeoJSON geometry or region."""
    try:
        stats = await service.compute_zonal_statistics(
            body.metric_id,
            date=body.date,
            geometry=body.geometry,
            region_id=body.region_id,
        )
    except MetricNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DatasetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ZonalCalculationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ZonalStatisticsResponse.from_domain(stats)


@router.post("/zonal-statistics/timeseries", response_model=ZonalTimeseriesResponse)
async def compute_zonal_timeseries_post(
    body: ZonalTimeseriesRequest,
    service: AnalyticsServiceDep,
) -> ZonalTimeseriesResponse:
    """Compute temporal time series of zonal statistics within a geometry or region."""
    try:
        ts = await service.compute_zonal_timeseries(
            body.metric_id,
            geometry=body.geometry,
            region_id=body.region_id,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except MetricNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DatasetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ZonalCalculationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ZonalTimeseriesResponse.from_domain(ts)


@router.get("/zonal-statistics/timeseries", response_model=ZonalTimeseriesResponse)
async def compute_zonal_timeseries_get(
    service: AnalyticsServiceDep,
    metric_id: Annotated[str, Query(alias="metricId")],
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    start_date: Annotated[str | None, Query(alias="startDate")] = None,
    end_date: Annotated[str | None, Query(alias="endDate")] = None,
) -> ZonalTimeseriesResponse:
    """Query temporal time series of zonal statistics for a saved region."""
    try:
        ts = await service.compute_zonal_timeseries(
            metric_id,
            region_id=region_id,
            start_date=start_date,
            end_date=end_date,
        )
    except MetricNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DatasetUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ZonalCalculationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return ZonalTimeseriesResponse.from_domain(ts)
