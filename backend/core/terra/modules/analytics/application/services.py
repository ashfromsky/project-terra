"""Application services for calculating zonal statistics and time series."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx

from terra.modules.analytics.domain.entities import (
    ZonalHistogram,
    ZonalStatistics,
    ZonalTimeseries,
    ZonalTimeseriesPoint,
)
from terra.modules.analytics.domain.exceptions import (
    DatasetUnavailableError,
    MetricNotFoundError,
    ZonalCalculationError,
)
from terra.modules.layers.application.services import _LAYER_GHS_SPECS, LayerCatalogService
from terra.modules.layers.domain.entities import LayerDefinition
from terra.modules.layers.domain.exceptions import LayerNotFoundError
from terra.modules.regions.domain.repositories import RegionRepository

logger = logging.getLogger(__name__)

_METRIC_ALIASES: dict[str, str] = {
    "ndvi": "ndvi-mod13q1",
    "evi": "evi-mod13q1",
    "lst": "lst-mod11a2",
    "lst_day": "lst-mod11a2",
    "precipitation": "precip-gpm-imerg",
    "precip": "precip-gpm-imerg",
    "soil_moisture": "soil-moisture-smap",
    "smap": "soil-moisture-smap",
}


class AnalyticsService:
    """Orchestrates raster zonal statistics and temporal time-series computation."""

    def __init__(
        self,
        layer_service: LayerCatalogService,
        *,
        ghs_base_url: str | None = None,
        ghs_timeout_seconds: float = 30.0,
        ghs_transport: httpx.AsyncBaseTransport | None = None,
        region_repo: RegionRepository | None = None,
    ) -> None:
        self._layer_service = layer_service
        self._ghs_base_url = ghs_base_url.rstrip("/") if ghs_base_url else None
        self._ghs_timeout_seconds = ghs_timeout_seconds
        self._ghs_transport = ghs_transport
        self._region_repo = region_repo

    async def _resolve_layer(self, metric_id: str) -> LayerDefinition:
        target_id = _METRIC_ALIASES.get(metric_id.lower(), metric_id)
        try:
            return await self._layer_service.get_layer(target_id)
        except LayerNotFoundError:
            # Try searching by matching shortName or variable
            layers = await self._layer_service.list_layers()
            for lyr in layers:
                if (
                    lyr.id.lower() == target_id.lower()
                    or lyr.variable.lower() == target_id.lower()
                    or lyr.short_name.lower() == target_id.lower()
                ):
                    return lyr
            raise MetricNotFoundError(f"Metric or layer '{metric_id}' not found.") from None

    async def _resolve_geometry(
        self,
        geometry: dict[str, Any] | None,
        region_id: UUID | None,
    ) -> dict[str, Any]:
        if geometry:
            if "type" in geometry and "coordinates" in geometry:
                return geometry
            if "geometry" in geometry and isinstance(geometry["geometry"], dict):
                return geometry["geometry"]
            raise ZonalCalculationError("Provided geometry does not contain type and coordinates.")

        if region_id and self._region_repo:
            region = await self._region_repo.get_by_id(region_id)
            if region:
                return region.geometry
            raise ZonalCalculationError(f"Region {region_id} not found.")

        raise ZonalCalculationError("Either geometry or regionId must be provided.")

    async def compute_zonal_statistics(
        self,
        metric_id: str,
        *,
        date: str | None = None,
        geometry: dict[str, Any] | None = None,
        region_id: UUID | None = None,
    ) -> ZonalStatistics:
        layer = await self._resolve_layer(metric_id)
        geom = await self._resolve_geometry(geometry, region_id)

        target_date = date
        if not target_date:
            if layer.available_dates:
                target_date = layer.available_dates[-1]
            elif layer.available_time_range and layer.available_time_range.end:
                target_date = layer.available_time_range.end
            else:
                target_date = "2024-06-01"

        dataset_id = layer.active_dataset_id
        if not dataset_id:
            raise DatasetUnavailableError(
                layer.unavailable_reason
                or f"No active raster dataset available for metric '{metric_id}'."
            )

        spec = _LAYER_GHS_SPECS.get(layer.id)
        unit_conversion = spec.unit_conversion if spec else None

        if not self._ghs_base_url:
            raise DatasetUnavailableError("Raster analysis service URL is not configured.")

        body: dict[str, Any] = {
            "geometry": geom,
            "variable": layer.variable,
            "timestamp": target_date,
        }
        if unit_conversion:
            body["unit_conversion"] = unit_conversion

        try:
            async with httpx.AsyncClient(
                base_url=self._ghs_base_url,
                timeout=self._ghs_timeout_seconds,
                transport=self._ghs_transport,
            ) as client:
                resp = await client.post(
                    f"/api/v1/datasets/{dataset_id}/zonal-statistics",
                    json=body,
                )
        except httpx.HTTPError as exc:
            logger.warning("GHS zonal-statistics request failed: %s", exc)
            raise ZonalCalculationError("Upstream raster service is unreachable.") from exc

        if resp.status_code >= 400:
            detail = f"Upstream raster service error: HTTP {resp.status_code}"
            try:
                err_json = resp.json()
                if isinstance(err_json, Mapping) and err_json.get("detail"):
                    detail = str(err_json["detail"])
            except ValueError:
                pass
            raise ZonalCalculationError(detail)

        data = resp.json()
        hist_data = data.get("histogram") or {}
        histogram = ZonalHistogram(
            bins=[float(b) for b in hist_data.get("bins", [])],
            counts=[int(c) for c in hist_data.get("counts", [])],
        )

        return ZonalStatistics(
            metric_id=layer.id,
            date=target_date,
            dataset_id=dataset_id,
            mean=data.get("mean"),
            median=data.get("median"),
            min=data.get("min"),
            max=data.get("max"),
            std=data.get("std"),
            q10=data.get("q10"),
            q25=data.get("q25"),
            q75=data.get("q75"),
            q90=data.get("q90"),
            valid_pixel_count=data.get("valid_pixel_count", 0),
            total_pixel_count=data.get("total_pixel_count", 0),
            valid_data_coverage=data.get("valid_data_coverage", 0.0),
            approx_area_km2=data.get("approx_area_km2", 0.0),
            units=layer.unit,
            histogram=histogram,
        )

    async def compute_zonal_timeseries(
        self,
        metric_id: str,
        *,
        geometry: dict[str, Any] | None = None,
        region_id: UUID | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_points: int = 24,
    ) -> ZonalTimeseries:
        layer = await self._resolve_layer(metric_id)
        geom = await self._resolve_geometry(geometry, region_id)

        available_dates = list(layer.available_dates)
        if start_date:
            available_dates = [d for d in available_dates if d >= start_date]
        if end_date:
            available_dates = [d for d in available_dates if d <= end_date]

        if not available_dates:
            # Fallback to single target date if available
            target_date = (
                layer.available_time_range.end
                if layer.available_time_range and layer.available_time_range.end
                else "2024-06-01"
            )
            available_dates = [target_date]

        if len(available_dates) > max_points:
            # Sample evenly across dates
            step = len(available_dates) / max_points
            available_dates = [available_dates[int(i * step)] for i in range(max_points)]

        semaphore = asyncio.Semaphore(4)

        async def _fetch_point(d: str) -> ZonalTimeseriesPoint | None:
            async with semaphore:
                try:
                    stats = await self.compute_zonal_statistics(
                        layer.id,
                        date=d,
                        geometry=geom,
                    )
                    return ZonalTimeseriesPoint(
                        date=d,
                        mean=stats.mean,
                        median=stats.median,
                        min=stats.min,
                        max=stats.max,
                        q25=stats.q25,
                        q75=stats.q75,
                        valid_data_coverage=stats.valid_data_coverage,
                    )
                except Exception as exc:
                    logger.warning("Failed to compute time series point for date %s: %s", d, exc)
                    return None

        results = await asyncio.gather(*[_fetch_point(d) for d in available_dates])
        points = [p for p in results if p is not None]
        points.sort(key=lambda pt: pt.date)

        return ZonalTimeseries(
            metric_id=layer.id,
            units=layer.unit,
            series=points,
        )
