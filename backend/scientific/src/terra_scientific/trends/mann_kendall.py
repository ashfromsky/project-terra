"""Mann-Kendall monotonic trend test with exact small-n, ties, and ACF policies."""

from datetime import datetime
from math import factorial

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.domain.enums import AutocorrelationPolicy, TrendDirection
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.domain.models.result import TrendResult
from terra_scientific.trends.autocorrelation import (
    diagnose_autocorrelation,
    hamed_rao_variance_factor,
    prewhiten_tfpw,
)
from terra_scientific.trends.sens_slope import (
    compute_sens_slope,
    elapsed_time_coordinate,
    mk_tie_corrected_variance,
)


def _exact_mk_p_value(n: int, s_stat: float) -> float:
    """Exact two-sided permutation p-value P(|S| >= |s_obs|) for untied n <= 10."""
    max_inv = n * (n - 1) // 2
    dp = [0] * (max_inv + 1)
    dp[0] = 1
    for m in range(2, n + 1):
        new_dp = [0] * (max_inv + 1)
        window = 0
        for k in range(max_inv + 1):
            window += dp[k]
            if k >= m:
                window -= dp[k - m]
            new_dp[k] = window
        dp = new_dp

    total_perms = factorial(n)
    abs_s = round(abs(s_stat))
    tail_count = 0
    for inv, count in enumerate(dp):
        s_val = max_inv - 2 * inv
        if abs(s_val) >= abs_s:
            tail_count += count
    return float(min(1.0, tail_count / total_perms))


def _mk_s_and_ties(y: NDArray[np.float64]) -> tuple[float, float, float]:
    n = int(y.size)
    s_val = 0.0
    for i in range(n - 1):
        diffs = y[i + 1 :] - y[i]
        s_val += float(np.sum(np.sign(diffs)))

    var_s = mk_tie_corrected_variance(y)
    d0 = float(n * (n - 1) // 2)
    _, counts = np.unique(y, return_counts=True)
    tie_pairs = sum(float(t * (t - 1) // 2) for t in counts if t > 1)
    denom = float(np.sqrt(max((d0 - tie_pairs) * d0, 0.0)))
    tau = s_val / denom if denom > 0.0 else 0.0
    return s_val, var_s, tau


def compute_mann_kendall(
    timestamps: list[datetime],
    values: NDArray[np.float64] | list[float | None],
    config: TrendConfig | None = None,
    *,
    dataset_id: str = "",
    variable_name: str = "variable",
    units: str = "units",
) -> TrendResult:
    """Evaluate Mann-Kendall monotonic trend, Sen's slope, and serial correlation."""
    cfg = config or TrendConfig()
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    valid_mask = np.isfinite(arr)
    valid_ts = [ts for ts, ok in zip(timestamps, valid_mask, strict=True) if ok]
    valid_y = arr[valid_mask]
    n_total = int(arr.size)
    n_valid = int(valid_y.size)

    if n_valid < cfg.min_samples or n_valid < 4:
        return TrendResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            variant=cfg.autocorrelation_policy.value,
            sample_count=n_total,
            valid_count=n_valid,
            direction=TrendDirection.INSUFFICIENT_DATA,
            slope_unit=f"{units}/{cfg.slope_time_unit}",
            alpha=cfg.alpha,
            warnings=[
                f"Valid observations ({n_valid}) fewer than minimum required ({cfg.min_samples})."
            ],
        )

    warnings: list[str] = []
    if n_valid < 10:
        warnings.append(
            f"Small sample size (n={n_valid} < 10); statistical power is limited and "
            "confidence intervals use asymptotic rank bounds."
        )

    sens = compute_sens_slope(
        valid_ts,
        valid_y,
        unit_label=units,
        time_unit=cfg.slope_time_unit,
        alpha=cfg.alpha,
    )
    x_elapsed = elapsed_time_coordinate(valid_ts, time_unit=cfg.slope_time_unit)
    residuals = valid_y - (sens.slope * x_elapsed + sens.intercept)
    acf_diag = diagnose_autocorrelation(
        residuals,
        max_lag=cfg.max_acf_lag,
        alpha=cfg.alpha,
        policy=cfg.autocorrelation_policy,
    )
    if acf_diag.significant_autocorrelation and (
        cfg.autocorrelation_policy == AutocorrelationPolicy.DIAGNOSTIC_ONLY
    ):
        warnings.append(
            "Significant serial autocorrelation detected in detrended residuals; standard "
            "Mann-Kendall p-values may overstate statistical significance."
        )

    work_y = valid_y
    variant_label = "standard_mk"

    if cfg.autocorrelation_policy == AutocorrelationPolicy.PREWHITEN_YUE_WANG:
        work_y, r1_pw = prewhiten_tfpw(x_elapsed, valid_y, sens.slope)
        variant_label = AutocorrelationPolicy.PREWHITEN_YUE_WANG.value
        warnings.append(
            f"Trend-free pre-whitening applied (lag-1 residual AR={r1_pw:.3f}); "
            "Sen's slope reflects original un-whitened series rate."
        )

    s_stat, base_var_s, tau = _mk_s_and_ties(work_y)
    var_s = base_var_s

    if cfg.autocorrelation_policy == AutocorrelationPolicy.HAMED_RAO_MODIFIED_MK:
        hr_factor = hamed_rao_variance_factor(residuals, alpha=cfg.alpha)
        var_s = base_var_s * hr_factor
        variant_label = AutocorrelationPolicy.HAMED_RAO_MODIFIED_MK.value
        sens = compute_sens_slope(
            valid_ts,
            valid_y,
            unit_label=units,
            time_unit=cfg.slope_time_unit,
            alpha=cfg.alpha,
            var_s_override=var_s,
        )
        warnings.append(f"Hamed-Rao variance scaling factor={hr_factor:.3f} applied.")

    z_stat = 0.0
    if var_s > 0.0:
        if s_stat > 0:
            z_stat = (s_stat - 1.0) / float(np.sqrt(var_s))
        elif s_stat < 0:
            z_stat = (s_stat + 1.0) / float(np.sqrt(var_s))

    has_ties = len(np.unique(work_y)) < work_y.size
    use_exact = (
        work_y.size <= 10
        and not has_ties
        and cfg.autocorrelation_policy == AutocorrelationPolicy.DIAGNOSTIC_ONLY
    )
    if use_exact:
        p_val = _exact_mk_p_value(int(work_y.size), s_stat)
        variant_label = "exact_small_sample_mk"
    elif var_s > 0.0:
        p_val = float(2.0 * norm.sf(abs(z_stat)))
    else:
        p_val = 1.0

    if p_val < cfg.alpha:
        direction = TrendDirection.INCREASING if s_stat > 0 else TrendDirection.DECREASING
    else:
        direction = TrendDirection.NO_TREND

    return TrendResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        variant=variant_label,
        sample_count=n_total,
        valid_count=n_valid,
        direction=direction,
        s_statistic=float(s_stat),
        var_s=float(var_s),
        z_statistic=float(z_stat),
        p_value=float(p_val),
        kendalls_tau=float(tau),
        sens_slope=float(sens.slope) if np.isfinite(sens.slope) else None,
        slope_unit=sens.unit,
        sens_intercept=float(sens.intercept) if np.isfinite(sens.intercept) else None,
        slope_ci_low=sens.ci_low,
        slope_ci_high=sens.ci_high,
        alpha=cfg.alpha,
        autocorrelation=acf_diag,
        warnings=warnings,
    )
