"""Separated Resistance, Recovery, Stability, and Sensitivity resilience dimensions."""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import StageStatus
from terra_scientific.domain.models.result import (
    EventResistanceDetail,
    PersistentAnomalyRun,
    RecoveryEventResult,
    ResilienceMetricsResult,
    ResilienceMetricValue,
)


def _to_float_array(values: NDArray[np.float64] | list[float | None] | None) -> NDArray[np.float64]:
    if values is None:
        return np.array([], dtype=np.float64)
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _extract_event_resistance_details(
    *,
    z_arr: NDArray[np.float64],
    events: list[RecoveryEventResult],
    timestamps: list[datetime] | None,
    disturbance_runs: list[PersistentAnomalyRun] | None,
) -> list[EventResistanceDetail]:
    details: list[EventResistanceDetail] = []
    if disturbance_runs is not None:
        for run in disturbance_runs:
            if (
                run.polarity == "negative_anomaly"
                and np.isfinite(run.peak_zscore)
                and run.peak_zscore < 0.0
            ):
                peak_neg = float(run.peak_zscore)
                details.append(
                    EventResistanceDetail(
                        event_start=run.start_timestamp,
                        event_end=run.end_timestamp,
                        peak_negative_zscore=peak_neg,
                        resistance=1.0 / (1.0 + abs(peak_neg)),
                    )
                )
        return details

    if not events or not np.any(np.isfinite(z_arr)):
        return details

    if timestamps is not None and len(timestamps) == z_arr.size:
        for ev in events:
            peak_window = np.array(
                [
                    z_arr[idx]
                    for idx, ts in enumerate(timestamps)
                    if ev.event_start <= ts <= ev.event_peak_timestamp
                    and np.isfinite(z_arr[idx])
                    and z_arr[idx] < 0.0
                ],
                dtype=np.float64,
            )
            if peak_window.size == 0:
                peak_window = np.array(
                    [
                        z_arr[idx]
                        for idx, ts in enumerate(timestamps)
                        if ev.event_start <= ts <= ev.observation_end
                        and np.isfinite(z_arr[idx])
                        and z_arr[idx] < 0.0
                    ],
                    dtype=np.float64,
                )
            if peak_window.size == 0:
                continue
            peak_neg = float(np.min(peak_window))
            details.append(
                EventResistanceDetail(
                    event_start=ev.event_start,
                    event_end=ev.observation_end,
                    event_peak_timestamp=ev.event_peak_timestamp,
                    peak_negative_zscore=peak_neg,
                    resistance=1.0 / (1.0 + abs(peak_neg)),
                )
            )
        return details

    if len(events) == 1:
        neg_z = z_arr[np.isfinite(z_arr) & (z_arr < 0.0)]
        if neg_z.size > 0:
            peak_neg = float(np.min(neg_z))
            ev = events[0]
            details.append(
                EventResistanceDetail(
                    event_start=ev.event_start,
                    event_end=ev.observation_end,
                    event_peak_timestamp=ev.event_peak_timestamp,
                    peak_negative_zscore=peak_neg,
                    resistance=1.0 / (1.0 + abs(peak_neg)),
                )
            )
    return details


def compute_resilience_dimensions(
    *,
    dataset_id: str,
    variable_name: str,
    deseasonalized_residuals: NDArray[np.float64] | list[float | None],
    standardized_residuals: NDArray[np.float64] | list[float | None] | None = None,
    zscores: NDArray[np.float64] | list[float | None] | None = None,
    timestamps: list[datetime] | None = None,
    disturbance_runs: list[PersistentAnomalyRun] | None = None,
    recovery_events: list[RecoveryEventResult] | None = None,
    sensitivity_slope: float | None = None,
    sensitivity_driver: str | None = None,
    sensitivity_unit: str = "response_units/driver_units",
) -> ResilienceMetricsResult:
    """Compute interpretable separated ecosystem proxy metrics without arbitrary TRI weights."""
    resid_arr = _to_float_array(deseasonalized_residuals)
    std_source = (
        standardized_residuals
        if standardized_residuals is not None
        else (zscores if zscores is not None else deseasonalized_residuals)
    )
    used_standardized = standardized_residuals is not None or zscores is not None
    std_arr = _to_float_array(std_source)
    finite_std = (
        std_arr[np.isfinite(std_arr)] if std_arr.size else resid_arr[np.isfinite(resid_arr)]
    )

    # 1. Resistance: mean(1 / (1 + |z_neg_peak,i|)) across eligible negative disturbance events.
    events = recovery_events or []
    z_arr = _to_float_array(zscores)
    event_details = _extract_event_resistance_details(
        z_arr=z_arr,
        events=events,
        timestamps=timestamps,
        disturbance_runs=disturbance_runs,
    )
    if event_details:
        res_val = float(np.mean([detail.resistance for detail in event_details]))
        resistance_metric = ResilienceMetricValue(
            dimension="resistance",
            available=True,
            status=StageStatus.COMPLETED,
            value=res_val,
            unit="dimensionless_(0..1]",
            formula="mean_i(1 / (1 + |z_neg_peak,i|))",
            interpretation=(
                f"Resistance {res_val:.3f} across {len(event_details)} negative disturbance "
                "event(s) reflects inverse negative-peak deflection relative to climatological "
                "baseline; values near 1 indicate smaller negative shock intensity."
            ),
            assumptions=[
                (
                    "Evaluated exclusively on negative disturbance episode peaks "
                    "relative to seasonal reference dispersion"
                )
            ],
            limitations=[
                (
                    "Conditioned on observed negative disturbance intensity; does not separate "
                    "mild stress from high exposure, and positive anomalies are excluded."
                )
            ],
            event_values=event_details,
        )
    else:
        resistance_metric = ResilienceMetricValue(
            dimension="resistance",
            available=False,
            status=StageStatus.UNAVAILABLE,
            value=None,
            unit="dimensionless_(0..1]",
            formula="mean_i(1 / (1 + |z_neg_peak,i|))",
            interpretation=(
                "No eligible negative disturbance episode detected; resistance cannot be "
                "quantified without an observed negative shock."
            ),
            limitations=["Absence of negative shock does not imply high structural resistance."],
        )

    # 2. Recovery: mean recovery completeness across evaluable negative disturbance events.
    evaluable_events = [ev for ev in events if ev.status != "insufficient_data"]
    if evaluable_events:
        mean_comp = float(np.mean([ev.recovery_completeness for ev in evaluable_events]))
        censored = any(ev.status == "incomplete_censored" for ev in evaluable_events)
        recovery_metric = ResilienceMetricValue(
            dimension="recovery",
            available=True,
            status=StageStatus.PARTIAL if censored else StageStatus.COMPLETED,
            value=mean_comp,
            unit="fraction_[0..1]",
            formula="mean((x_end_or_rec - x_peak) / (x_pre - x_peak))",
            interpretation=(
                f"Observed post-event completeness {mean_comp:.2f}"
                + (" (includes right-censored events)." if censored else ".")
            ),
            assumptions=["Evaluated on deseasonalized departures outside phenological green-up"],
            limitations=["Reflects proxy return rather than biophysical species recovery."],
        )
    elif events:
        recovery_metric = ResilienceMetricValue(
            dimension="recovery",
            available=False,
            status=StageStatus.INSUFFICIENT_DATA,
            value=None,
            unit="fraction_[0..1]",
            formula="mean((x_end_or_rec - x_peak) / (x_pre - x_peak))",
            interpretation=(
                "Detected disturbance episode(s) lacked sufficient pre-event baseline or "
                "post-event observations to evaluate recovery."
            ),
            limitations=["Requires finite pre-disturbance baseline and post-peak observations."],
        )
    else:
        recovery_metric = ResilienceMetricValue(
            dimension="recovery",
            available=False,
            status=StageStatus.SKIPPED,
            value=None,
            unit="fraction_[0..1]",
            formula="mean((x_end_or_rec - x_peak) / (x_pre - x_peak))",
            interpretation="No disturbance episode available to evaluate post-event recovery.",
            limitations=["Requires detected departure episode with pre/post window."],
        )

    # 3. Stability: 1 / (1 + std(standardized_residuals)) for unit-invariant dimensionless spread.
    stab_formula = (
        "1 / (1 + std(standardized_deseasonalized_residuals))"
        if used_standardized
        else "1 / (1 + std(deseasonalized_residuals))"
    )
    if finite_std.size >= 6:
        resid_std = float(np.std(finite_std, ddof=1))
        stab_val = 1.0 / (1.0 + resid_std)
        stab_limitations = [
            "High stability can coexist with slow degraded steady states; always check trends.",
            (
                "Scale invariance depends on seasonal reference dispersion estimates "
                "(MAD/SD per season bucket)."
            ),
        ]
        if resid_std <= 1e-12:
            stab_limitations.append(
                "Zero dispersion across standardized residuals yields stability=1.0; inspect "
                "input variability and climatology sample coverage."
            )
        stability_metric = ResilienceMetricValue(
            dimension="stability",
            available=True,
            status=StageStatus.COMPLETED,
            value=stab_val,
            unit="dimensionless_(0..1]",
            formula=stab_formula,
            interpretation=(
                f"Residual temporal stability {stab_val:.3f} (standardized residual std="
                f"{resid_std:.4f})."
            ),
            assumptions=[
                (
                    "Seasonally standardized residual variance summarizes dimensionless "
                    "non-seasonal volatility"
                )
            ],
            limitations=stab_limitations,
        )
    else:
        stability_metric = ResilienceMetricValue(
            dimension="stability",
            available=False,
            status=StageStatus.INSUFFICIENT_DATA,
            value=None,
            unit="dimensionless_(0..1]",
            formula=stab_formula,
            interpretation=(
                "Insufficient valid standardized residuals to characterize temporal stability."
            ),
        )

    # 4. Sensitivity: OLS regression slope on environmental driver anomaly when available.
    if sensitivity_slope is not None and np.isfinite(sensitivity_slope):
        driver_lbl = sensitivity_driver or "environmental_driver"
        sensitivity_metric = ResilienceMetricValue(
            dimension="sensitivity",
            available=True,
            status=StageStatus.COMPLETED,
            value=float(sensitivity_slope),
            unit=sensitivity_unit,
            formula="OLS slope of response anomaly against forcing driver anomaly",
            interpretation=(
                f"Estimated statistical co-variation slope {sensitivity_slope:.4f} "
                f"({sensitivity_unit}) against {driver_lbl}."
            ),
            assumptions=["Linear relationship on aligned deseasonalized observations"],
            limitations=[
                (
                    "Statistical sensitivity coefficient is non-causal and ignores "
                    "unmeasured confounders."
                )
            ],
        )
    else:
        sensitivity_metric = ResilienceMetricValue(
            dimension="sensitivity",
            available=False,
            status=StageStatus.UNAVAILABLE,
            value=None,
            unit=sensitivity_unit,
            formula="OLS slope of response anomaly against forcing driver anomaly",
            interpretation="No compatible meteorological or hydrological driver dataset supplied.",
            limitations=["Requires valid cross-variable overlap to estimate response sensitivity."],
        )

    return ResilienceMetricsResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        resistance=resistance_metric,
        recovery=recovery_metric,
        stability=stability_metric,
        sensitivity=sensitivity_metric,
    )
