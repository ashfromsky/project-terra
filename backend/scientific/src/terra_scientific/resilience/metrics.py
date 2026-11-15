"""Separated Resistance, Recovery, Stability, and Sensitivity resilience dimensions."""

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import StageStatus
from terra_scientific.domain.models.result import (
    RecoveryEventResult,
    ResilienceMetricsResult,
    ResilienceMetricValue,
)


def compute_resilience_dimensions(
    *,
    dataset_id: str,
    variable_name: str,
    deseasonalized_residuals: NDArray[np.float64] | list[float | None],
    zscores: NDArray[np.float64] | list[float | None] | None = None,
    recovery_events: list[RecoveryEventResult] | None = None,
    sensitivity_slope: float | None = None,
    sensitivity_driver: str | None = None,
    sensitivity_unit: str = "standardized_response/driver",
) -> ResilienceMetricsResult:
    """Compute interpretable separated ecosystem proxy metrics without arbitrary TRI weights."""
    resid_arr = np.array(
        [np.nan if v is None else float(v) for v in deseasonalized_residuals],
        dtype=np.float64,
    )
    finite_resid = resid_arr[np.isfinite(resid_arr)]

    # 1. Resistance: 1 / (1 + max(|z_peak|)) across disturbance episodes.
    events = recovery_events or []
    z_arr = (
        np.array([np.nan if v is None else float(v) for v in zscores], dtype=np.float64)
        if zscores is not None
        else np.array([], dtype=np.float64)
    )
    if events and np.any(np.isfinite(z_arr)):
        peak_abs_z = float(np.nanmax(np.abs(z_arr)))
        res_val = 1.0 / (1.0 + peak_abs_z)
        resistance_metric = ResilienceMetricValue(
            dimension="resistance",
            available=True,
            status=StageStatus.COMPLETED,
            value=res_val,
            unit="dimensionless_(0..1]",
            formula="1 / (1 + max(|z_peak|))",
            interpretation=(
                f"Resistance {res_val:.3f} indicates inverse relative deflection under observed "
                "anomaly shock; values near 1 indicate smaller departures from seasonal baseline."
            ),
            assumptions=["Perturbation intensity scaled relative to seasonal reference dispersion"],
            limitations=[
                (
                    "Conditioned on disturbance intensity; does not separate mild stress "
                    "from high exposure."
                )
            ],
        )
    else:
        resistance_metric = ResilienceMetricValue(
            dimension="resistance",
            available=False,
            status=StageStatus.SKIPPED,
            value=None,
            unit="dimensionless_(0..1]",
            formula="1 / (1 + max(|z_peak|))",
            interpretation=(
                "No negative disturbance episode detected; resistance requires an "
                "observed perturbation."
            ),
            limitations=["Absence of shock does not establish high structural resistance."],
        )

    # 2. Recovery: mean recovery completeness across observed events.
    if events:
        mean_comp = float(np.mean([ev.recovery_completeness for ev in events]))
        censored = any(ev.status == "incomplete_censored" for ev in events)
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

    # 3. Stability: 1 / (1 + std(deseasonalized residuals)) avoiding unbounded 1/sigma spikes.
    if finite_resid.size >= 6:
        resid_std = float(np.std(finite_resid, ddof=1))
        stab_val = 1.0 / (1.0 + resid_std)
        stability_metric = ResilienceMetricValue(
            dimension="stability",
            available=True,
            status=StageStatus.COMPLETED,
            value=stab_val,
            unit="dimensionless_(0..1]",
            formula="1 / (1 + std(deseasonalized_residuals))",
            interpretation=(
                f"Residual temporal stability {stab_val:.3f} (residual std={resid_std:.4f})."
            ),
            assumptions=["Desesonalized residual variance summarizes non-seasonal volatility"],
            limitations=[
                "High stability can coexist with slow degraded steady states; always check trends."
            ],
        )
    else:
        stability_metric = ResilienceMetricValue(
            dimension="stability",
            available=False,
            status=StageStatus.INSUFFICIENT_DATA,
            value=None,
            unit="dimensionless_(0..1]",
            formula="1 / (1 + std(deseasonalized_residuals))",
            interpretation="Insufficient valid residuals to characterize temporal stability.",
        )

    # 4. Sensitivity: bivariate/OLS regression slope on driver forcing when available.
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
                f"against {driver_lbl}."
            ),
            assumptions=["Linear relationship on deseasonalized common timestamps"],
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
