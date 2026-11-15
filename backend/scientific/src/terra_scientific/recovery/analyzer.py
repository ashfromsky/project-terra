"""Event-centered post-disturbance recovery trajectory analyzer."""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.models.request import RecoveryConfig
from terra_scientific.domain.models.result import RecoveryEventResult
from terra_scientific.domain.models.temporal import SECONDS_PER_DAY
from terra_scientific.trends.sens_slope import SECONDS_PER_YEAR


def analyze_post_event_recovery(
    timestamps: list[datetime],
    series_values: NDArray[np.float64] | list[float | None],
    *,
    event_start_idx: int,
    event_peak_idx: int | None = None,
    config: RecoveryConfig | None = None,
    dataset_id: str = "",
    variable_name: str = "variable",
    unit_label: str = "units",
    is_deseasonalized: bool = True,
    next_event_idx: int | None = None,
) -> RecoveryEventResult:
    """Measure pre-event baseline, deficit depth, elapsed recovery rate, and completeness.

    Recovery is confirmed only after ``config.confirmation_steps`` consecutive valid
    observations remain at or above the recovery threshold within the window bounded
    by ``next_event_idx``. Any missing/non-finite observation or sub-threshold step resets
    confirmation so transient spikes or cross-event rebounds are not misclassified.
    """
    cfg = config or RecoveryConfig()
    arr = np.array([np.nan if v is None else float(v) for v in series_values], dtype=np.float64)
    n = int(arr.size)
    if n == 0 or len(timestamps) != n:
        raise ValueError("timestamps and series_values must be non-empty and equal length")
    if event_start_idx < 0 or event_start_idx >= n:
        raise ValueError(f"event_start_idx ({event_start_idx}) out of bounds for length {n}")
    if next_event_idx is not None and next_event_idx <= event_start_idx:
        raise ValueError("next_event_idx must be strictly greater than event_start_idx")

    warnings: list[str] = []

    if cfg.require_deseasonalized and not is_deseasonalized:
        warnings.append(
            "Recovery computed on non-deseasonalized series; seasonal phenological green-up may "
            "be conflated with ecological recovery."
        )

    search_end = min(next_event_idx, n) if next_event_idx is not None else n
    pre_start = max(0, event_start_idx - cfg.pre_event_window_steps)
    pre_slice = arr[pre_start:event_start_idx]
    pre_valid = pre_slice[np.isfinite(pre_slice)]

    seasonal_caveat = (
        f"Evaluated on seasonally adjusted anomalies with {cfg.confirmation_steps}-step "
        "consecutive confirmation; recovery measures sustained return toward expected seasonal "
        "state rather than ecosystem species composition."
        if is_deseasonalized
        else (
            f"Computed without prior seasonal deseasonalization ({cfg.confirmation_steps}-step "
            "consecutive confirmation)."
        )
    )

    if pre_valid.size == 0:
        peak_idx = (
            event_start_idx if event_peak_idx is None else min(event_peak_idx, search_end - 1)
        )
        peak_val = float(arr[peak_idx]) if np.isfinite(arr[peak_idx]) else 0.0
        return RecoveryEventResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            event_start=timestamps[event_start_idx],
            event_peak_timestamp=timestamps[peak_idx],
            observation_end=timestamps[search_end - 1],
            pre_event_baseline=0.0,
            event_minimum_or_peak=peak_val,
            deficit_magnitude=0.0,
            elapsed_recovery_rate=None,
            rate_unit=f"{unit_label}/year",
            time_to_recovery_days=None,
            recovery_completeness=0.0,
            post_event_residual=None,
            status="insufficient_data",
            deseasonalized_series_used=is_deseasonalized,
            seasonal_caveat=seasonal_caveat,
            warnings=[
                *warnings,
                "Insufficient valid pre-event observations to establish pre-disturbance baseline.",
            ],
        )

    pre_baseline = float(np.median(pre_valid))

    if event_peak_idx is None:
        event_window = arr[event_start_idx:search_end]
        if np.any(np.isfinite(event_window)):
            rel_min = int(np.nanargmin(event_window))
            peak_idx = event_start_idx + rel_min
        else:
            peak_idx = event_start_idx
    else:
        if event_peak_idx < event_start_idx or event_peak_idx >= search_end:
            raise ValueError("event_peak_idx must fall within [event_start_idx, next_event_idx)")
        peak_idx = event_peak_idx

    peak_val = float(arr[peak_idx]) if np.isfinite(arr[peak_idx]) else pre_baseline
    deficit = max(pre_baseline - peak_val, 0.0)

    post_slice = arr[peak_idx + 1 : search_end]
    post_ts = timestamps[peak_idx + 1 : search_end]
    valid_post_mask = np.isfinite(post_slice)
    valid_post_vals = post_slice[valid_post_mask]
    valid_post_ts = [t for t, ok in zip(post_ts, valid_post_mask, strict=True) if ok]

    if deficit <= 1e-12 or valid_post_vals.size < cfg.min_post_event_steps:
        return RecoveryEventResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            event_start=timestamps[event_start_idx],
            event_peak_timestamp=timestamps[peak_idx],
            observation_end=timestamps[search_end - 1],
            pre_event_baseline=pre_baseline,
            event_minimum_or_peak=peak_val,
            deficit_magnitude=deficit,
            elapsed_recovery_rate=None,
            rate_unit=f"{unit_label}/year",
            time_to_recovery_days=None,
            recovery_completeness=0.0,
            post_event_residual=None,
            status="incomplete_censored",
            deseasonalized_series_used=is_deseasonalized,
            seasonal_caveat=seasonal_caveat,
            warnings=[*warnings, "Insufficient post-event steps or zero event deficit."],
        )

    recovery_target = pre_baseline - (1.0 - cfg.recovery_fraction_threshold) * deficit
    consecutive_ok = 0
    candidate_start_idx: int | None = None
    confirmed_start_idx: int | None = None

    for idx_global in range(peak_idx + 1, search_end):
        val_step = arr[idx_global]
        if not np.isfinite(val_step):
            consecutive_ok = 0
            candidate_start_idx = None
            continue
        if val_step >= recovery_target:
            if consecutive_ok == 0:
                candidate_start_idx = idx_global
            consecutive_ok += 1
            if consecutive_ok >= cfg.confirmation_steps:
                confirmed_start_idx = candidate_start_idx
                break
        else:
            consecutive_ok = 0
            candidate_start_idx = None

    peak_ts = timestamps[peak_idx]
    if confirmed_start_idx is not None:
        rec_ts = timestamps[confirmed_start_idx]
        rec_val = float(arr[confirmed_start_idx])
        elapsed_sec = max((rec_ts - peak_ts).total_seconds(), 1.0)
        rate = (rec_val - peak_val) / (elapsed_sec / SECONDS_PER_YEAR)
        ttr_days = elapsed_sec / SECONDS_PER_DAY
        comp = float(np.clip((rec_val - peak_val) / deficit, 0.0, 1.5))
        return RecoveryEventResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            event_start=timestamps[event_start_idx],
            event_peak_timestamp=peak_ts,
            observation_end=valid_post_ts[-1],
            pre_event_baseline=pre_baseline,
            event_minimum_or_peak=peak_val,
            deficit_magnitude=deficit,
            elapsed_recovery_rate=float(rate),
            rate_unit=f"{unit_label}/year",
            time_to_recovery_days=float(ttr_days),
            recovery_completeness=float(min(comp, 1.0)),
            post_event_residual=float(valid_post_vals[-1] - pre_baseline),
            status="recovered",
            deseasonalized_series_used=is_deseasonalized,
            seasonal_caveat=seasonal_caveat,
            warnings=warnings,
        )

    end_ts = valid_post_ts[-1]
    end_val = float(valid_post_vals[-1])
    elapsed_years = np.array(
        [(t - peak_ts).total_seconds() / SECONDS_PER_YEAR for t in [peak_ts, *valid_post_ts]],
        dtype=np.float64,
    )
    traj_vals = np.array([peak_val, *valid_post_vals], dtype=np.float64)
    if float(np.ptp(elapsed_years)) > 0.0 and traj_vals.size >= 2:
        slope_rate: float | None = float(np.polyfit(elapsed_years, traj_vals, 1)[0])
    else:
        slope_rate = None
    completeness = float(np.clip((end_val - peak_val) / deficit, 0.0, 1.0))
    status = (
        "incomplete_censored"
        if (slope_rate is not None and slope_rate > 0.0) or completeness > 0.1
        else "not_recovered"
    )
    censor_msg = (
        "Recovery window bounded by subsequent disturbance prior to confirmed recovery."
        if next_event_idx is not None and search_end < n
        else (
            "Observation window ended prior to reaching confirmed recovery threshold "
            "(right-censored)."
        )
    )

    return RecoveryEventResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        event_start=timestamps[event_start_idx],
        event_peak_timestamp=peak_ts,
        observation_end=end_ts,
        pre_event_baseline=pre_baseline,
        event_minimum_or_peak=peak_val,
        deficit_magnitude=deficit,
        elapsed_recovery_rate=slope_rate,
        rate_unit=f"{unit_label}/year",
        time_to_recovery_days=None,
        recovery_completeness=completeness,
        post_event_residual=float(end_val - pre_baseline),
        status=status,
        deseasonalized_series_used=is_deseasonalized,
        seasonal_caveat=seasonal_caveat,
        warnings=[*warnings, censor_msg],
    )
