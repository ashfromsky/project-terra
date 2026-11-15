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
    """Measure pre-event baseline, deficit depth, elapsed recovery rate, and completeness."""
    cfg = config or RecoveryConfig()
    arr = np.array([np.nan if v is None else float(v) for v in series_values], dtype=np.float64)
    n = int(arr.size)
    warnings: list[str] = []

    if cfg.require_deseasonalized and not is_deseasonalized:
        warnings.append(
            "Recovery computed on non-deseasonalized series; seasonal phenological green-up may "
            "be conflated with ecological recovery."
        )

    pre_start = max(0, event_start_idx - cfg.pre_event_window_steps)
    pre_slice = arr[pre_start:event_start_idx]
    pre_valid = pre_slice[np.isfinite(pre_slice)]
    pre_baseline = float(np.median(pre_valid)) if pre_valid.size > 0 else 0.0

    search_end = next_event_idx if next_event_idx is not None else n
    if event_peak_idx is None:
        event_window = arr[event_start_idx:search_end]
        if np.any(np.isfinite(event_window)):
            rel_min = int(np.nanargmin(event_window))
            peak_idx = event_start_idx + rel_min
        else:
            peak_idx = event_start_idx
    else:
        peak_idx = event_peak_idx

    peak_val = float(arr[peak_idx]) if np.isfinite(arr[peak_idx]) else pre_baseline
    deficit = max(pre_baseline - peak_val, 0.0)

    post_slice = arr[peak_idx + 1 : search_end]
    post_ts = timestamps[peak_idx + 1 : search_end]
    valid_post_mask = np.isfinite(post_slice)
    valid_post_vals = post_slice[valid_post_mask]
    valid_post_ts = [t for t, ok in zip(post_ts, valid_post_mask, strict=True) if ok]

    seasonal_caveat = (
        "Evaluated on seasonally adjusted anomalies; recovery measures return toward expected "
        "seasonal state rather than ecosystem species composition."
        if is_deseasonalized
        else "Computed without prior seasonal deseasonalization."
    )

    if deficit <= 1e-12 or valid_post_vals.size < cfg.min_post_event_steps:
        return RecoveryEventResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            event_start=timestamps[event_start_idx],
            event_peak_timestamp=timestamps[peak_idx],
            observation_end=timestamps[min(search_end, n) - 1],
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
    recovered_pos: int | None = None
    for idx_post, val_post in enumerate(valid_post_vals):
        if val_post >= recovery_target:
            recovered_pos = idx_post
            break

    peak_ts = timestamps[peak_idx]
    if recovered_pos is not None:
        rec_ts = valid_post_ts[recovered_pos]
        rec_val = float(valid_post_vals[recovered_pos])
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
    slope_rate = float(np.polyfit(elapsed_years, traj_vals, 1)[0])
    completeness = float(np.clip((end_val - peak_val) / deficit, 0.0, 1.0))
    status = "incomplete_censored" if slope_rate > 0.0 or completeness > 0.1 else "not_recovered"

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
        warnings=[
            *warnings,
            "Observation window ended prior to reaching recovery threshold (right-censored).",
        ],
    )
