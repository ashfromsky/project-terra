"""Raster zonal statistics computation on physical scientific COG arrays."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.mask import mask as rio_mask
from shapely import transform as shapely_transform  # type: ignore[import-untyped]
from shapely.geometry import mapping, shape  # type: ignore[import-untyped]

from geospatial_harmonization.application.cog_publisher import CogPublisher
from geospatial_harmonization.domain.exceptions import DomainError
from geospatial_harmonization.domain.models.dataset import SpatialDataset
from geospatial_harmonization.domain.ports import DatasetRepository, StoragePort
from geospatial_harmonization.readers import ReaderRegistry

logger = logging.getLogger(__name__)


class ZonalStatsError(DomainError):
    """Raised when computing zonal statistics fails."""


def _reproject_geometry(geom: Any, src_crs: str, dst_crs: str) -> Any:
    if src_crs == dst_crs:
        return geom
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return shapely_transform(
        geom,
        lambda coords: np.column_stack(transformer.transform(coords[:, 0], coords[:, 1])),
    )


def _compute_histogram(
    values: np.ndarray[Any, Any], bin_count: int = 15
) -> dict[str, list[float | int]]:
    if values.size == 0:
        return {"bins": [], "counts": []}
    counts, bin_edges = np.histogram(values, bins=bin_count)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    return {
        "bins": [round(float(b), 4) for b in bin_centers],
        "counts": [int(c) for c in counts],
    }


def _calculate_pixel_area_km2(res_x: float, res_y: float, crs_str: str) -> float:
    """Estimate pixel area in square kilometers."""
    if "4326" in crs_str:
        # Approximate degree to km at mid-latitudes
        km_per_deg = 111.32
        return abs(res_x * km_per_deg * res_y * km_per_deg)
    # Projected meters
    return abs(res_x * res_y) / 1_000_000.0


def compute_zonal_statistics_sync(
    cog_target: str,
    geo_json_geometry: dict[str, Any],
    variable_name: str,
    units: str,
) -> dict[str, Any]:
    """Extract physical raster values inside GeoJSON polygon and compute zonal summary."""
    try:
        poly_wgs84 = shape(geo_json_geometry)
        if not poly_wgs84.is_valid:
            poly_wgs84 = poly_wgs84.buffer(0)
    except Exception as exc:
        raise ZonalStatsError(f"Invalid GeoJSON geometry: {exc}") from exc

    with rasterio.open(cog_target) as src:
        raster_crs = str(src.crs or "EPSG:4326")
        poly_raster = _reproject_geometry(poly_wgs84, "EPSG:4326", raster_crs)

        # Check bounds overlap
        poly_bounds = poly_raster.bounds
        if rasterio.coords.disjoint_bounds(poly_bounds, src.bounds):
            return {
                "variableName": variable_name,
                "units": units,
                "crs": raster_crs,
                "mean": None,
                "median": None,
                "min": None,
                "max": None,
                "std": None,
                "q10": None,
                "q25": None,
                "q75": None,
                "q90": None,
                "validPixelCount": 0,
                "totalPixelCount": 0,
                "validDataCoverage": 0.0,
                "approxAreaKm2": 0.0,
                "histogram": {"bins": [], "counts": []},
                "warnings": ["Selected area does not intersect the dataset bounding box."],
            }

        try:
            out_image, out_transform = rio_mask(
                src,
                [mapping(poly_raster)],
                crop=True,
                all_touched=False,
                nodata=np.nan,
            )
        except ValueError:
            # Polygon inside bounds but touches 0 pixel centroids with all_touched=False
            out_image, out_transform = rio_mask(
                src,
                [mapping(poly_raster)],
                crop=True,
                all_touched=True,
                nodata=np.nan,
            )

        data = out_image[0] if out_image.ndim == 3 else out_image
        total_pixels = int(data.size)
        valid_mask = np.isfinite(data)
        if src.nodata is not None and not np.isnan(src.nodata):
            valid_mask &= data != src.nodata

        valid_vals = data[valid_mask].astype(np.float64, copy=False)
        valid_count = int(valid_vals.size)
        coverage = float(valid_count / total_pixels) if total_pixels > 0 else 0.0

        res_x = abs(out_transform.a)
        res_y = abs(out_transform.e)
        pixel_area_km2 = _calculate_pixel_area_km2(res_x, res_y, raster_crs)
        approx_area = round(valid_count * pixel_area_km2, 2)

        warnings: list[str] = []
        if valid_count < 4:
            warnings.append("Insufficient valid sample size (<4 pixels) for robust statistics.")
        if coverage < 0.25 and valid_count > 0:
            warnings.append(f"Low valid data coverage ({coverage * 100:.1f}%) in selected area.")

        if valid_count == 0:
            return {
                "variableName": variable_name,
                "units": units,
                "crs": raster_crs,
                "mean": None,
                "median": None,
                "min": None,
                "max": None,
                "std": None,
                "q10": None,
                "q25": None,
                "q75": None,
                "q90": None,
                "validPixelCount": 0,
                "totalPixelCount": total_pixels,
                "validDataCoverage": 0.0,
                "approxAreaKm2": 0.0,
                "histogram": {"bins": [], "counts": []},
                "warnings": [
                    *warnings,
                    "No valid scientific observations found in the selected polygon.",
                ],
            }

        mean_val = float(np.mean(valid_vals))
        median_val = float(np.median(valid_vals))
        min_val = float(np.min(valid_vals))
        max_val = float(np.max(valid_vals))
        std_val = float(np.std(valid_vals, ddof=1)) if valid_count > 1 else 0.0
        q10, q25, q75, q90 = np.percentile(valid_vals, [10.0, 25.0, 75.0, 90.0])
        hist_data = _compute_histogram(valid_vals)

        return {
            "variableName": variable_name,
            "units": units,
            "crs": raster_crs,
            "mean": round(mean_val, 4),
            "median": round(median_val, 4),
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "std": round(std_val, 4),
            "q10": round(float(q10), 4),
            "q25": round(float(q25), 4),
            "q75": round(float(q75), 4),
            "q90": round(float(q90), 4),
            "validPixelCount": valid_count,
            "totalPixelCount": total_pixels,
            "validDataCoverage": round(coverage, 4),
            "approxAreaKm2": approx_area,
            "histogram": hist_data,
            "warnings": warnings,
        }


async def compute_dataset_zonal_statistics(
    dataset: SpatialDataset,
    geometry: dict[str, Any],
    storage: StoragePort | None,
    readers: ReaderRegistry,
    datasets_repo: DatasetRepository | None,
    *,
    variable: str | None = None,
    timestamp: str | None = None,
    unit_conversion: str | None = None,
) -> dict[str, Any]:
    """Asynchronously resolve or publish COG and calculate raster zonal statistics."""
    publisher = CogPublisher(storage=storage, readers=readers, datasets=datasets_repo)
    cog_res = await publisher.get_or_publish_cog(
        dataset,
        variable=variable,
        timestamp=timestamp,
        unit_conversion=unit_conversion,
    )

    cog_target: str
    if cog_res.local_path is not None and cog_res.local_path.is_file():
        cog_target = str(cog_res.local_path)
    elif storage is not None and hasattr(storage, "generate_presigned_download_url"):
        presigned = await storage.generate_presigned_download_url(
            cog_res.storage_key, expires_in=600
        )
        cog_target = presigned or cog_res.asset.uri
    else:
        cog_target = cog_res.asset.uri

    var_name = variable or next(iter(dataset.variables.keys()))
    units = dataset.units.get(var_name, "unitless")

    result = await asyncio.to_thread(
        compute_zonal_statistics_sync,
        cog_target,
        geometry,
        var_name,
        units,
    )
    result["datasetId"] = str(dataset.dataset_id)
    result["timestamp"] = timestamp or dataset.temporal_metadata.start.strftime("%Y-%m-%d")
    return result
