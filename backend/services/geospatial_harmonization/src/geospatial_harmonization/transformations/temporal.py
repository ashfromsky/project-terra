"""Temporal alignment, rate-to-depth integration, and coverage-aware aggregation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    InvalidTemporalSpecError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.temporal import (
    TemporalAggregationKind,
    TemporalSpec,
    require_tz_aware,
)


@dataclass(frozen=True, slots=True)
class TemporalAggregationResult:
    """Aggregated temporal array paired with per-pixel observation coverage metrics."""

    data: NDArray[np.float32]
    coverage_fraction: NDArray[np.float32]
    valid_pixels: int
    total_pixels: int
    temporal_spec: TemporalSpec
    warnings: tuple[str, ...] = ()


def normalize_to_utc(dt: datetime, field_name: str = "timestamp") -> datetime:
    """Validate timezone awareness and normalize a datetime to UTC."""
    require_tz_aware(dt, field_name)
    return dt.astimezone(UTC)


def validate_coverage_threshold(min_coverage_fraction: float) -> None:
    """Ensure minimum temporal coverage threshold lies within [0, 1]."""
    if not 0.0 <= min_coverage_fraction <= 1.0:
        raise QualityPolicyViolationError("min_coverage_fraction must lie within [0, 1]")


def _stack_to_float64(
    arrays: Sequence[NDArray[np.generic]], nodata: float | int | None
) -> NDArray[np.float64]:
    if not arrays:
        raise IncompatibleDatasetError("At least one array is required for temporal aggregation")
    base_shape = arrays[0].shape
    stacked = np.empty((len(arrays), *base_shape), dtype=np.float64)
    for idx, arr in enumerate(arrays):
        if arr.shape != base_shape:
            raise IncompatibleDatasetError(
                f"Array shape {arr.shape} at index {idx} != expected {base_shape}"
            )
        buf = arr.astype(np.float64, copy=True)
        if nodata is not None:
            nd = float(nodata)
            if np.isnan(nd):
                buf[np.isnan(buf)] = np.nan
            elif np.issubdtype(arr.dtype, np.floating):
                with np.errstate(over="ignore"):
                    nd_typed = arr.dtype.type(nd)
                if not np.isfinite(nd) or np.isfinite(nd_typed):
                    buf[arr == nd_typed] = np.nan
            else:
                buf[buf == nd] = np.nan
        stacked[idx] = buf
    return stacked


def check_temporal_alignment(
    specs: Sequence[TemporalSpec], target: TemporalSpec
) -> tuple[str, ...]:
    """Validate observation specs against target support and report compositing warnings."""
    if not specs:
        raise InvalidTemporalSpecError("Temporal aggregation requires at least one TemporalSpec")
    t_start = normalize_to_utc(target.start, "target.start")
    t_end = normalize_to_utc(target.end, "target.end")
    warnings: list[str] = []
    for spec in specs:
        s_start = normalize_to_utc(spec.start, "spec.start")
        s_end = normalize_to_utc(spec.end, "spec.end")
        if s_end < t_start or s_start > t_end:
            raise InvalidTemporalSpecError(
                f"Observation window [{s_start.isoformat()}, {s_end.isoformat()}] "
                f"does not overlap target [{t_start.isoformat()}, {t_end.isoformat()}]"
            )
        if spec.semantics == "composite" and target.semantics != "composite":
            msg = (
                f"Aggregating {spec.composite_days}-day composite observations into non-composite "
                "target support preserves composited temporal smoothing."
            )
            if msg not in warnings:
                warnings.append(msg)
    return tuple(warnings)


def integrate_rate_to_depth(
    rate_arrays: Sequence[NDArray[np.generic]],
    interval_specs: Sequence[TemporalSpec],
    target: TemporalSpec,
    *,
    min_coverage_fraction: float = 0.0,
    nodata: float | int | None = None,
) -> TemporalAggregationResult:
    """Integrate interval rate observations (e.g., mm/hr) to depth (mm) over interval durations."""
    validate_coverage_threshold(min_coverage_fraction)
    if len(rate_arrays) != len(interval_specs):
        raise IncompatibleDatasetError("rate_arrays and interval_specs lengths must match")
    warnings = list(check_temporal_alignment(interval_specs, target))

    durations_hr = np.empty(len(interval_specs), dtype=np.float64)
    for idx, spec in enumerate(interval_specs):
        if spec.semantics != "interval":
            raise InvalidTemporalSpecError(
                "Rate-to-depth integration requires 'interval' semantics with finite duration"
            )
        durations_hr[idx] = spec.duration_seconds / 3600.0

    stacked = _stack_to_float64(rate_arrays, nodata)
    valid_mask = np.isfinite(stacked)
    depths = np.where(valid_mask, stacked * durations_hr[:, *(None,) * (stacked.ndim - 1)], 0.0)
    coverage = np.mean(valid_mask, axis=0).astype(np.float32)
    total_depth = np.sum(depths, axis=0)

    has_any = np.any(valid_mask, axis=0)
    sufficient = has_any & (coverage >= min_coverage_fraction)
    out = np.where(sufficient, total_depth, np.nan).astype(np.float32)
    if np.any(has_any & ~sufficient):
        warnings.append(
            "Masked pixels below min_coverage_fraction during rate-to-depth integration."
        )

    valid_px = int(np.count_nonzero(np.isfinite(out)))
    return TemporalAggregationResult(
        out, coverage, valid_px, int(out.size), target, tuple(warnings)
    )


def aggregate_temporal_stack(
    arrays: Sequence[NDArray[np.generic]],
    specs: Sequence[TemporalSpec],
    target: TemporalSpec,
    aggregation: TemporalAggregationKind,
    *,
    weights: Sequence[NDArray[np.floating]] | None = None,
    min_coverage_fraction: float = 0.5,
    nodata: float | int | None = None,
) -> TemporalAggregationResult:
    """Aggregate an observation stack using explicit temporal semantics and coverage masks."""
    if aggregation == "none":
        raise IncompatibleDatasetError("Cannot aggregate with aggregation='none'")
    if aggregation == "rate_to_depth_sum":
        return integrate_rate_to_depth(
            arrays, specs, target, min_coverage_fraction=min_coverage_fraction, nodata=nodata
        )

    validate_coverage_threshold(min_coverage_fraction)
    if len(arrays) != len(specs):
        raise IncompatibleDatasetError("arrays and specs lengths must match")
    warnings = list(check_temporal_alignment(specs, target))
    stacked = _stack_to_float64(arrays, nodata)
    valid_mask = np.isfinite(stacked)
    coverage = np.mean(valid_mask, axis=0).astype(np.float32)
    sufficient = np.any(valid_mask, axis=0) & (coverage >= min_coverage_fraction)

    safe = np.where(sufficient[None, ...], stacked, np.nan)
    with np.errstate(all="ignore"):
        if aggregation == "mean":
            agg: NDArray[np.float64] = np.asarray(np.nanmean(safe, axis=0), dtype=np.float64)
        elif aggregation == "sum":
            agg = np.asarray(np.nansum(safe, axis=0), dtype=np.float64)
        elif aggregation == "min":
            agg = np.asarray(np.nanmin(safe, axis=0), dtype=np.float64)
        elif aggregation == "max":
            agg = np.asarray(np.nanmax(safe, axis=0), dtype=np.float64)
        elif aggregation == "median":
            agg = np.asarray(np.nanmedian(safe, axis=0), dtype=np.float64)
        elif aggregation == "quality_weighted_mean":
            if weights is None or len(weights) != len(arrays):
                raise IncompatibleDatasetError(
                    "quality_weighted_mean requires matching weight arrays"
                )
            w_arr = _stack_to_float64(weights, nodata)
            w_eff = np.where(valid_mask & np.isfinite(w_arr) & (w_arr > 0.0), w_arr, 0.0)
            w_sum = np.sum(w_eff, axis=0)
            num = np.sum(np.where(valid_mask, stacked * w_eff, 0.0), axis=0)
            agg = np.divide(num, w_sum, out=np.full_like(num, np.nan), where=w_sum > 0.0)
        else:
            raise IncompatibleDatasetError(f"Unsupported temporal aggregation: {aggregation}")

    out = np.where(sufficient, agg, np.nan).astype(np.float32)
    if np.any(np.any(valid_mask, axis=0) & ~sufficient):
        warnings.append("Masked pixels below min_coverage_fraction during temporal aggregation.")
    valid_px = int(np.count_nonzero(np.isfinite(out)))
    return TemporalAggregationResult(
        out, coverage, valid_px, int(out.size), target, tuple(warnings)
    )
