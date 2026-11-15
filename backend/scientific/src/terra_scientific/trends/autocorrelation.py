"""Serial autocorrelation diagnostics, Hamed-Rao factor, and Yue-Wang pre-whitening."""

import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2, norm, rankdata

from terra_scientific.domain.enums import AutocorrelationPolicy
from terra_scientific.domain.models.result import AutocorrelationDiagnostics


def compute_sample_acf(series: NDArray[np.float64], max_lag: int = 12) -> list[float | None]:
    """Compute sample autocorrelation function up to max_lag over finite observations."""
    finite = series[np.isfinite(series)]
    n = int(finite.size)
    if n < 4:
        return []
    mean_v = float(np.mean(finite))
    centered = finite - mean_v
    denom = float(np.dot(centered, centered))
    if denom <= 1e-15:
        return [None for _ in range(min(max_lag, n - 2))]

    limit = min(max_lag, max(1, n - 2))
    acf: list[float | None] = []
    for lag in range(1, limit + 1):
        num = float(np.dot(centered[lag:], centered[:-lag]))
        acf.append(num / denom)
    return acf


def hamed_rao_variance_factor(residuals: NDArray[np.float64], alpha: float = 0.05) -> float:
    """Compute Hamed & Rao (1998) variance scaling ratio n/n_s* from ranked residuals."""
    n = int(residuals.size)
    if n < 5:
        return 1.0
    ranks = rankdata(residuals)
    ranks_c = ranks - np.mean(ranks)
    denom = float(np.dot(ranks_c, ranks_c))
    if denom <= 1e-15:
        return 1.0

    z_crit = float(norm.ppf(1.0 - alpha / 2.0))
    threshold = z_crit / np.sqrt(float(n))
    weighted_sum = 0.0
    for k in range(1, n - 2):
        r_k = float(np.dot(ranks_c[k:], ranks_c[:-k]) / denom)
        if abs(r_k) > threshold:
            weighted_sum += float((n - k) * (n - k - 1) * (n - k - 2)) * r_k

    factor = 1.0 + (2.0 / float(n * (n - 1) * (n - 2))) * weighted_sum
    return float(max(factor, 0.25))


def prewhiten_tfpw(
    x_elapsed: NDArray[np.float64],
    values: NDArray[np.float64],
    slope: float,
) -> tuple[NDArray[np.float64], float]:
    """Apply Trend-Free Pre-Whitening (Yue et al. 2002) using lag-1 residual AR(1)."""
    n = int(values.size)
    if n < 4:
        return values.copy(), 0.0
    detrended = values - slope * x_elapsed
    mean_d = float(np.mean(detrended))
    centered = detrended - mean_d
    denom = float(np.dot(centered, centered))
    if denom <= 1e-15:
        return values.copy(), 0.0
    r1 = float(np.dot(centered[1:], centered[:-1]) / denom)
    r1 = float(np.clip(r1, -0.99, 0.99))

    pw_detrended = np.empty(n - 1, dtype=np.float64)
    for idx in range(1, n):
        pw_detrended[idx - 1] = detrended[idx] - r1 * detrended[idx - 1]
    blended = pw_detrended + slope * x_elapsed[1:]
    return blended, r1


def diagnose_autocorrelation(
    residuals: NDArray[np.float64],
    *,
    max_lag: int = 12,
    alpha: float = 0.05,
    policy: AutocorrelationPolicy = AutocorrelationPolicy.DIAGNOSTIC_ONLY,
) -> AutocorrelationDiagnostics:
    """Compute lag-1/ACF, Ljung-Box Q test, and effective sample size diagnostics."""
    finite = residuals[np.isfinite(residuals)]
    n = int(finite.size)
    acf_list = compute_sample_acf(finite, max_lag=max_lag)
    lag1 = acf_list[0] if acf_list else None

    q_stat: float | None = None
    q_p: float | None = None
    valid_acf = [
        (idx + 1, val)
        for idx, val in enumerate(acf_list)
        if val is not None and (n - (idx + 1)) > 0
    ]
    if n >= 6 and valid_acf:
        q_val = float(n * (n + 2)) * sum((val**2) / float(n - k) for k, val in valid_acf)
        q_stat = q_val
        q_p = float(chi2.sf(q_val, df=len(valid_acf)))

    eff_n: float | None = None
    if n >= 4 and acf_list:
        denom_sum = 0.0
        for k, val in enumerate(acf_list, start=1):
            if val is not None:
                denom_sum += (1.0 - float(k) / float(n)) * val
        eff_n = float(np.clip(float(n) / max(1.0 + 2.0 * denom_sum, 1.0), 1.0, float(n)))

    z_crit = float(norm.ppf(1.0 - alpha / 2.0))
    lag1_sig = lag1 is not None and abs(lag1) > z_crit / np.sqrt(max(float(n), 1.0))
    q_sig = q_p is not None and q_p < alpha

    return AutocorrelationDiagnostics(
        lag1_acf=lag1,
        acf_values=acf_list,
        ljung_box_stat=q_stat,
        ljung_box_p=q_p,
        effective_sample_size=eff_n,
        significant_autocorrelation=bool(lag1_sig or q_sig),
        policy_applied=policy.value,
    )
