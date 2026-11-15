"""Area-weighted zonal aggregation and temporal zonal series extraction."""

import warnings as py_warnings
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.models.dataset import ScientificGridStack
from terra_scientific.domain.models.result import SpatialStatsResult


def compute_grid_weights(stack: ScientificGridStack) -> NDArray[np.float64]:
    """Resolve explicit pixel area weights or cos(latitude) weights on geographic grids."""
    _, height, width = stack.data.shape
    if stack.cell_areas_m2 is not None:
        return np.asarray(stack.cell_areas_m2, dtype=np.float64)
    if (
        not stack.spatial_support.is_projected
        and stack.spatial_support.latitudes is not None
        and len(stack.spatial_support.latitudes) == height
    ):
        lats_rad = np.deg2rad(np.asarray(stack.spatial_support.latitudes, dtype=np.float64))
        col_weights = np.clip(np.cos(lats_rad), 1e-6, None)
        return np.repeat(col_weights[:, None], width, axis=1)
    return np.ones((height, width), dtype=np.float64)


def compute_zonal_statistics(
    stack: ScientificGridStack,
    *,
    time_index: int | None = None,
) -> SpatialStatsResult:
    """Compute area-weighted mean, quantiles, dispersion, and AOI pixel coverage."""
    if time_index is not None:
        slice_2d = stack.data[time_index]
    else:
        with py_warnings.catch_warnings():
            py_warnings.simplefilter("ignore", RuntimeWarning)
            slice_2d = np.nanmean(stack.data, axis=0)
    weights_2d = compute_grid_weights(stack)
    aoi = stack.aoi_mask if stack.aoi_mask is not None else np.ones(slice_2d.shape, dtype=bool)
    total_aoi_pixels = int(np.sum(aoi))

    valid_mask = aoi & np.isfinite(slice_2d) & np.isfinite(weights_2d) & (weights_2d > 0.0)
    valid_vals = slice_2d[valid_mask]
    valid_weights = weights_2d[valid_mask]
    valid_count = int(valid_vals.size)
    coverage = valid_count / total_aoi_pixels if total_aoi_pixels > 0 else 0.0

    warnings: list[str] = []
    if (
        stack.spatial_support.native_footprint_m is not None
        and stack.spatial_support.nominal_resolution_m is not None
        and stack.spatial_support.native_footprint_m > stack.spatial_support.nominal_resolution_m
    ):
        warnings.append(
            f"Nominal posting ({stack.spatial_support.nominal_resolution_m:.0f} m) is finer than "
            f"native sensor footprint ({stack.spatial_support.native_footprint_m:.0f} m)."
        )

    if valid_count == 0:
        return SpatialStatsResult(
            dataset_id=stack.dataset_id,
            variable_name=stack.variable.name,
            units=stack.variable.units,
            crs=stack.spatial_support.crs,
            area_weighted_mean=None,
            unweighted_mean=None,
            median=None,
            std=None,
            iqr=None,
            q10=None,
            q25=None,
            q75=None,
            q90=None,
            valid_pixel_count=0,
            total_pixel_count=total_aoi_pixels,
            coverage_fraction=0.0,
            warnings=[*warnings, "No valid pixels inside AOI mask."],
        )

    w_mean = float(np.sum(valid_vals * valid_weights) / np.sum(valid_weights))
    u_mean = float(np.mean(valid_vals))
    std_v = float(np.std(valid_vals, ddof=1)) if valid_count > 1 else 0.0
    q10, q25, q50, q75, q90 = np.percentile(valid_vals, [10.0, 25.0, 50.0, 75.0, 90.0])

    return SpatialStatsResult(
        dataset_id=stack.dataset_id,
        variable_name=stack.variable.name,
        units=stack.variable.units,
        crs=stack.spatial_support.crs,
        area_weighted_mean=w_mean,
        unweighted_mean=u_mean,
        median=float(q50),
        std=std_v,
        iqr=float(q75 - q25),
        q10=float(q10),
        q25=float(q25),
        q75=float(q75),
        q90=float(q90),
        valid_pixel_count=valid_count,
        total_pixel_count=total_aoi_pixels,
        coverage_fraction=coverage,
        warnings=warnings,
    )


def extract_area_weighted_series(
    stack: ScientificGridStack,
    *,
    min_spatial_coverage: float = 0.5,
) -> tuple[list[datetime], NDArray[np.float64]]:
    """Collapse 3D stack [T, Y, X] into area-weighted 1D series gating low spatial coverage."""
    t_steps = stack.data.shape[0]
    weights = compute_grid_weights(stack)
    aoi = (
        stack.aoi_mask if stack.aoi_mask is not None else np.ones(stack.data.shape[1:], dtype=bool)
    )
    total_aoi = max(int(np.sum(aoi)), 1)

    series = np.full(t_steps, np.nan, dtype=np.float64)
    for t in range(t_steps):
        frame = stack.data[t]
        valid = aoi & np.isfinite(frame) & np.isfinite(weights) & (weights > 0.0)
        v_count = int(np.sum(valid))
        if v_count == 0 or (v_count / total_aoi) < min_spatial_coverage:
            continue
        series[t] = float(np.sum(frame[valid] * weights[valid]) / np.sum(weights[valid]))
    return list(stack.timestamps), series
