"""Standardized, robust, percentile, and persistent anomaly detection."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.baselines.climatology import MAD_NORMAL_CONSTANT
from terra_scientific.domain.enums import BaselineType, SeasonalGrouping
from terra_scientific.domain.models.request import AnomalyConfig
from terra_scientific.domain.models.result import (
    AnomalyResult,
    BaselineClimatologyResult,
    ClimatologyBin,
    PersistentAnomalyRun,
)
from terra_scientific.temporal.seasonal import seasonal_group_keys


def _extract_reference_samples(
    timestamps: list[datetime],
    values: NDArray[np.float64],
    group_keys: list[int],
    climatology: BaselineClimatologyResult,
) -> dict[int, NDArray[np.float64]]:
    ref_buckets: dict[int, list[float]] = defaultdict(list)
    for ts, gkey, val in zip(timestamps, group_keys, values, strict=True):
        if climatology.reference_start <= ts <= climatology.reference_end and np.isfinite(val):
            ref_buckets[gkey].append(float(val))
    return {k: np.asarray(v, dtype=np.float64) for k, v in ref_buckets.items() if v}


def _find_persistent_runs(
    timestamps: list[datetime],
    z_values: list[float | None],
    raw_anomalies: list[float | None],
    config: AnomalyConfig,
) -> list[PersistentAnomalyRun]:
    runs: list[PersistentAnomalyRun] = []
    n = len(timestamps)
    idx = 0

    while idx < n:
        z_cur = z_values[idx]
        if z_cur is None or abs(z_cur) < config.zscore_threshold:
            idx += 1
            continue

        polarity = "positive_anomaly" if z_cur > 0 else "negative_anomaly"
        sign_positive = z_cur > 0
        start_idx = idx
        step_zs: list[float] = []
        step_raws: list[float] = []

        while idx < n:
            z_next = z_values[idx]
            if z_next is None:
                break
            same_sign = (
                z_next >= config.zscore_threshold
                if sign_positive
                else (z_next <= -config.zscore_threshold)
            )
            if not same_sign:
                break
            step_zs.append(z_next)
            raw_v = raw_anomalies[idx]
            if raw_v is not None:
                step_raws.append(raw_v)
            idx += 1

        if len(step_zs) >= config.min_persistence_steps:
            peak_z = max(step_zs) if sign_positive else min(step_zs)
            runs.append(
                PersistentAnomalyRun(
                    start_timestamp=timestamps[start_idx],
                    end_timestamp=timestamps[idx - 1],
                    step_count=len(step_zs),
                    polarity=polarity,
                    peak_zscore=float(peak_z),
                    mean_zscore=float(np.mean(step_zs)),
                    cumulative_departure=float(np.sum(step_raws)) if step_raws else 0.0,
                )
            )
    return runs


def detect_anomalies(
    timestamps: list[datetime],
    values: Sequence[float | None] | NDArray[np.float64],
    climatology: BaselineClimatologyResult,
    config: AnomalyConfig | None = None,
    *,
    composite_days: int | None = None,
    reference_samples: Mapping[int, NDArray[np.float64]] | None = None,
) -> AnomalyResult:
    """Compute raw anomalies, z-scores, robust z-scores, percentiles, and persistent runs."""
    cfg = config or AnomalyConfig()
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    grouping = SeasonalGrouping(climatology.seasonal_grouping)
    group_keys, _ = seasonal_group_keys(timestamps, grouping, composite_days=composite_days)
    bins_by_key: dict[int, ClimatologyBin] = {b.bin_key: b for b in climatology.bins}

    warnings: list[str] = list(climatology.warnings)
    if reference_samples is not None:
        ref_map = dict(reference_samples)
    else:
        ref_map = _extract_reference_samples(timestamps, arr, group_keys, climatology)

    is_cv = climatology.baseline_type == BaselineType.CROSS_VALIDATED.value
    year_bin_vals: dict[int, list[tuple[int, float]]] = defaultdict(list)
    if is_cv:
        for ts, gkey, val in zip(timestamps, group_keys, arr, strict=True):
            if np.isfinite(val):
                year_bin_vals[gkey].append((ts.year, float(val)))

    raw_out: list[float | None] = []
    std_z_out: list[float | None] = []
    rob_z_out: list[float | None] = []
    pct_out: list[float | None] = []
    zero_var_warning = False

    for ts, gkey, val in zip(timestamps, group_keys, arr, strict=True):
        if not np.isfinite(val):
            raw_out.append(None)
            std_z_out.append(None)
            rob_z_out.append(None)
            pct_out.append(None)
            continue

        if is_cv:
            oof = np.asarray(
                [v for yr, v in year_bin_vals.get(gkey, []) if yr != ts.year],
                dtype=np.float64,
            )
            if oof.size < 2:
                raw_out.append(None)
                std_z_out.append(None)
                rob_z_out.append(None)
                pct_out.append(None)
                continue
            b_mean = float(np.mean(oof))
            b_med = float(np.median(oof))
            b_std: float | None = float(np.std(oof, ddof=1))
            b_mad: float | None = MAD_NORMAL_CONSTANT * float(np.median(np.abs(oof - b_med)))
            ref_arr: NDArray[np.float64] | None = oof
        else:
            cbin = bins_by_key.get(gkey)
            if cbin is None or cbin.mean is None or cbin.median is None:
                raw_out.append(None)
                std_z_out.append(None)
                rob_z_out.append(None)
                pct_out.append(None)
                continue
            b_mean = cbin.mean
            b_med = cbin.median
            b_std = cbin.std
            b_mad = cbin.mad
            ref_arr = ref_map.get(gkey)

        raw_diff = float(val - b_mean)
        raw_out.append(raw_diff)

        if b_std is not None and b_std > 1e-12:
            std_z_out.append(float((val - b_mean) / b_std))
        else:
            std_z_out.append(None)
            zero_var_warning = True

        if b_mad is not None and b_mad > 1e-12:
            rob_z_out.append(float((val - b_med) / b_mad))
        else:
            rob_z_out.append(None)
            zero_var_warning = True

        if ref_arr is not None and ref_arr.size > 0:
            pct_out.append(float(np.mean(ref_arr <= val) * 100.0))
        elif b_std is not None and b_std > 1e-12:
            pct_out.append(float(norm.cdf((val - b_mean) / b_std) * 100.0))
        else:
            pct_out.append(None)

    if zero_var_warning:
        warnings.append(
            "Zero variance or zero MAD encountered in one or more seasonal bins; "
            "corresponding z-scores left null."
        )

    active_z = (
        [r if r is not None else s for r, s in zip(rob_z_out, std_z_out, strict=True)]
        if cfg.use_robust_default
        else std_z_out
    )
    runs = _find_persistent_runs(timestamps, active_z, raw_out, cfg)

    return AnomalyResult(
        dataset_id=climatology.dataset_id,
        variable_name=climatology.variable_name,
        units=climatology.units,
        timestamps=list(timestamps),
        raw_anomalies=raw_out,
        standard_zscores=std_z_out,
        robust_zscores=rob_z_out,
        percentiles=pct_out,
        persistent_runs=runs,
        warnings=warnings,
    )
