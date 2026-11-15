"""Cross-variable association, lagged correlation, OLS regression, and compatibility guards."""

from collections import defaultdict
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm, pearsonr, spearmanr
from scipy.stats import t as student_t

from terra_scientific.domain.enums import DataSourceId
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.dataset import VariableMetadata
from terra_scientific.domain.models.request import CrossVariableConfig
from terra_scientific.domain.models.result import (
    CrossVariablePairResult,
    CrossVariableResult,
    LagCorrelationEntry,
    MultipleRegressionSummary,
)

SeriesBundle = tuple[
    list[datetime],
    NDArray[np.float64],
    VariableMetadata,
    DataSourceId,
    float | None,
]


def _align_two_series(
    ts_a: list[datetime],
    vals_a: NDArray[np.float64],
    ts_b: list[datetime],
    vals_b: NDArray[np.float64],
) -> tuple[list[datetime], NDArray[np.float64], NDArray[np.float64]]:
    """Inner-join two time series on UTC timestamp preserving sorted chronological order."""
    map_b: dict[datetime, float] = {}
    for ts, v in zip(ts_b, vals_b, strict=True):
        map_b[ts] = float(v)

    common_ts: list[datetime] = []
    aligned_a: list[float] = []
    aligned_b: list[float] = []
    for ts, va in zip(ts_a, vals_a, strict=True):
        if ts in map_b:
            common_ts.append(ts)
            aligned_a.append(float(va))
            aligned_b.append(map_b[ts])
    return (
        common_ts,
        np.asarray(aligned_a, dtype=np.float64),
        np.asarray(aligned_b, dtype=np.float64),
    )


def _deseasonalize_by_month(
    timestamps: list[datetime],
    values: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Subtract calendar-month mean when at least 2 years span the stratum."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts, val in zip(timestamps, values, strict=True):
        if np.isfinite(val):
            buckets[ts.month].append(float(val))
    means = {
        m: float(np.mean(vs)) if len(vs) >= 2 else float(np.nanmean(values))
        for m, vs in buckets.items()
    }
    out = np.full(values.shape, np.nan, dtype=np.float64)
    for idx, (ts, val) in enumerate(zip(timestamps, values, strict=True)):
        if np.isfinite(val) and ts.month in means:
            out[idx] = val - means[ts.month]
    return out


def _fisher_z_ci(r: float, n: int, alpha: float) -> tuple[float | None, float | None]:
    if n <= 3 or abs(r) >= 0.999999:
        return None, None
    z_r = 0.5 * float(np.log((1.0 + r) / (1.0 - r)))
    se = 1.0 / float(np.sqrt(n - 3))
    z_crit = float(norm.ppf(1.0 - alpha / 2.0))
    low = float(np.tanh(z_r - z_crit * se))
    high = float(np.tanh(z_r + z_crit * se))
    return low, high


def _safe_correlations(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
) -> tuple[float | None, float | None, float | None, float | None, int]:
    valid = np.isfinite(x) & np.isfinite(y)
    xv = x[valid]
    yv = y[valid]
    n = int(xv.size)
    if n < 4 or float(np.std(xv)) <= 1e-12 or float(np.std(yv)) <= 1e-12:
        return None, None, None, None, n
    pr, pp = pearsonr(xv, yv)
    sr, sp = spearmanr(xv, yv)
    return float(pr), float(pp), float(sr), float(sp), n


def _bivariate_ols(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    min_samples: int,
) -> tuple[float | None, float | None, float | None]:
    """Compute OLS regression slope y ~ 1 + x with standard error and two-sided p-value."""
    valid = np.isfinite(x) & np.isfinite(y)
    xv = x[valid]
    yv = y[valid]
    n = int(xv.size)
    if n < max(min_samples, 3):
        return None, None, None
    dx = xv - float(np.mean(xv))
    sxx = float(np.dot(dx, dx))
    if sxx <= 1e-15:
        return None, None, None
    dy = yv - float(np.mean(yv))
    slope = float(np.dot(dx, dy) / sxx)
    intercept = float(np.mean(yv)) - slope * float(np.mean(xv))
    resid = yv - (intercept + slope * xv)
    ss_res = float(np.dot(resid, resid))
    dof = n - 2
    se = float(np.sqrt(max(ss_res / float(dof), 0.0) / sxx))
    if se > 1e-15:
        t_stat = slope / se
        p_val = float(2.0 * student_t.sf(abs(t_stat), df=dof))
    else:
        p_val = 0.0 if abs(slope) > 1e-15 else 1.0
    return slope, se, p_val


def compute_partial_correlation(
    target: NDArray[np.float64],
    predictor: NDArray[np.float64],
    confounders: NDArray[np.float64],
) -> tuple[float, float]:
    """Compute partial Pearson correlation controlling for confounders via OLS residualization."""
    t_arr = np.asarray(target, dtype=np.float64)
    p_arr = np.asarray(predictor, dtype=np.float64)
    c_mat = np.asarray(confounders, dtype=np.float64)
    if c_mat.ndim == 1:
        c_mat = c_mat[:, None]

    valid = np.isfinite(t_arr) & np.isfinite(p_arr) & np.all(np.isfinite(c_mat), axis=1)
    y = t_arr[valid]
    x = p_arr[valid]
    z = c_mat[valid]
    n = int(y.size)
    k = z.shape[1]
    if n <= k + 3:
        return float("nan"), float("nan")

    design = np.column_stack([np.ones(n, dtype=np.float64), z])
    beta_y, *_ = np.linalg.lstsq(design, y, rcond=None)
    beta_x, *_ = np.linalg.lstsq(design, x, rcond=None)
    res_y = y - design @ beta_y
    res_x = x - design @ beta_x
    denom = float(np.sqrt(np.dot(res_y, res_y) * np.dot(res_x, res_x)))
    if denom <= 1e-15:
        return 0.0, 1.0
    r_part = float(np.clip(np.dot(res_y, res_x) / denom, -0.999999, 0.999999))
    dof = n - k - 2
    t_stat = r_part * float(np.sqrt(dof / max(1.0 - r_part**2, 1e-15)))
    p_val = float(2.0 * student_t.sf(abs(t_stat), df=dof))
    return r_part, p_val


def _multiple_regression(
    response_name: str,
    response_vec: NDArray[np.float64],
    predictor_vecs: dict[str, NDArray[np.float64]],
) -> MultipleRegressionSummary | None:
    if len(predictor_vecs) < 2:
        return None
    pred_names = list(predictor_vecs)
    cols = [predictor_vecs[k] for k in pred_names]
    x_raw = np.column_stack(cols)
    valid = np.isfinite(response_vec) & np.all(np.isfinite(x_raw), axis=1)
    y = response_vec[valid]
    x = x_raw[valid]
    n, p = x.shape
    if n <= p + 2:
        return None

    design = np.column_stack([np.ones(n, dtype=np.float64), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    y_hat = design @ beta
    resid = y - y_hat
    ss_res = float(np.dot(resid, resid))
    ss_tot = float(np.dot(y - np.mean(y), y - np.mean(y)))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-15 else 0.0
    adj_r2 = 1.0 - (1.0 - r2) * float(n - 1) / float(n - p - 1)

    sigma2 = ss_res / float(n - p - 1)
    xtx_inv = np.linalg.pinv(design.T @ design)
    se_all = np.sqrt(np.clip(np.diag(xtx_inv) * sigma2, 0.0, None))

    coefs: dict[str, float] = {}
    std_errs: dict[str, float] = {}
    p_vals: dict[str, float] = {}
    vifs: dict[str, float] = {}
    warnings: list[str] = []

    for j, name in enumerate(pred_names, start=1):
        coef_val = float(beta[j])
        se_val = float(se_all[j])
        coefs[name] = coef_val
        std_errs[name] = se_val
        if se_val > 1e-12:
            t_val = coef_val / se_val
            p_vals[name] = float(2.0 * student_t.sf(abs(t_val), df=n - p - 1))
        else:
            p_vals[name] = 1.0

        # Predictor collinearity VIF = 1 / (1 - R2_j)
        other_cols = np.delete(x, j - 1, axis=1)
        sub_design = np.column_stack([np.ones(n, dtype=np.float64), other_cols])
        sub_beta, *_ = np.linalg.lstsq(sub_design, x[:, j - 1], rcond=None)
        sub_res = x[:, j - 1] - sub_design @ sub_beta
        sub_tot = float(
            np.dot(x[:, j - 1] - np.mean(x[:, j - 1]), x[:, j - 1] - np.mean(x[:, j - 1]))
        )
        sub_r2 = 1.0 - float(np.dot(sub_res, sub_res)) / sub_tot if sub_tot > 1e-15 else 0.0
        vif = 1.0 / max(1.0 - sub_r2, 1e-6)
        vifs[name] = float(vif)
        if vif >= 5.0:
            warnings.append(f"High multicollinearity (VIF={vif:.2f}) for predictor '{name}'.")

    return MultipleRegressionSummary(
        response_variable=response_name,
        predictor_variables=pred_names,
        sample_count=n,
        r_squared=float(r2),
        adjusted_r_squared=float(adj_r2),
        coefficients=coefs,
        standard_errors=std_errs,
        p_values=p_vals,
        vif=vifs,
        warnings=warnings,
    )


def analyze_cross_variables(
    *,
    response_name: str,
    response_series: SeriesBundle,
    predictors: dict[str, SeriesBundle],
    config: CrossVariableConfig | None = None,
) -> CrossVariableResult:
    """Analyze pairwise, lagged, partial, and OLS multiple relationships without causal claims."""
    cfg = config or CrossVariableConfig()
    resp_ts, resp_vals, resp_meta, resp_src, resp_res = response_series
    all_warnings: list[str] = []

    has_gpm = resp_src == DataSourceId.GPM_IMERG or any(
        b[3] == DataSourceId.GPM_IMERG for b in predictors.values()
    )
    has_power_precip = any(
        b[3] == DataSourceId.NASA_POWER and "PRECTOTCORR" in b[2].name.upper()
        for b in predictors.values()
    ) or (resp_src == DataSourceId.NASA_POWER and "PRECTOTCORR" in resp_meta.name.upper())
    if has_gpm and has_power_precip and not cfg.allow_power_precip_with_gpm:
        raise ScientificInputError(
            "NASA POWER PRECTOTCORR cannot be analyzed alongside or substituted for GPM IMERG "
            "precipitation unless allow_power_precip_with_gpm=True.",
            code="power_precip_gpm_conflict",
        )

    aligned_vectors: dict[str, NDArray[np.float64]] = {}
    pairwise_results: list[CrossVariablePairResult] = []

    for pred_name, pred_bundle in predictors.items():
        p_ts, p_vals, p_meta, _, p_res = pred_bundle
        joined_ts, r_al, p_al = _align_two_series(resp_ts, resp_vals, p_ts, p_vals)
        compat_warnings: list[str] = []
        slope_unit = f"{resp_meta.units}/{p_meta.units}" if resp_meta.units and p_meta.units else ""

        if resp_res is not None and p_res is not None and min(resp_res, p_res) > 0.0:
            ratio = max(resp_res, p_res) / min(resp_res, p_res)
            if ratio >= 5.0:
                compat_warnings.append(
                    f"Spatial resolution disparity ({ratio:.1f}x) between '{response_name}' "
                    f"(~{resp_res:.0f} m) and '{pred_name}' (~{p_res:.0f} m)."
                )

        if cfg.deseasonalize and len(joined_ts) >= 12:
            r_work = _deseasonalize_by_month(joined_ts, r_al)
            p_work = _deseasonalize_by_month(joined_ts, p_al)
        else:
            r_work = r_al
            p_work = p_al

        pr, pp, sr, sp, n_ov = _safe_correlations(p_work, r_work)
        if n_ov < cfg.min_overlap_samples:
            compat_warnings.append(
                f"Overlap sample size ({n_ov}) is below minimum ({cfg.min_overlap_samples})."
            )
            pairwise_results.append(
                CrossVariablePairResult(
                    response_variable=response_name,
                    driver_variable=pred_name,
                    deseasonalized=cfg.deseasonalize,
                    overlap_count=n_ov,
                    pearson_r=None,
                    pearson_p=None,
                    spearman_rho=None,
                    spearman_p=None,
                    slope_unit=slope_unit,
                    compatibility_warnings=compat_warnings,
                )
            )
            continue

        ols_slope, ols_se, ols_p = _bivariate_ols(p_work, r_work, cfg.min_overlap_samples)
        ci_low, ci_high = _fisher_z_ci(pr, n_ov, cfg.alpha) if pr is not None else (None, None)

        lag_entries: list[LagCorrelationEntry] = []
        best_lag: int | None = None
        best_r: float | None = None
        max_lag = min(cfg.max_lag_steps, max(0, len(joined_ts) - cfg.min_overlap_samples))
        for lag in range(0, max_lag + 1):
            if lag == 0:
                x_slice, y_slice = p_work, r_work
            else:
                x_slice, y_slice = p_work[:-lag], r_work[lag:]
            l_pr, l_pp, l_sr, l_sp, l_n = _safe_correlations(x_slice, y_slice)
            lag_entries.append(
                LagCorrelationEntry(
                    lag_steps=lag,
                    sample_count=l_n,
                    pearson_r=l_pr,
                    pearson_p=l_pp,
                    spearman_rho=l_sr,
                    spearman_p=l_sp,
                )
            )
            if l_pr is not None and (best_r is None or abs(l_pr) > abs(best_r)):
                best_r = l_pr
                best_lag = lag

        aligned_vectors[pred_name] = p_work
        pairwise_results.append(
            CrossVariablePairResult(
                response_variable=response_name,
                driver_variable=pred_name,
                deseasonalized=cfg.deseasonalize,
                overlap_count=n_ov,
                pearson_r=pr,
                pearson_p=pp,
                pearson_ci_low=ci_low,
                pearson_ci_high=ci_high,
                spearman_rho=sr,
                spearman_p=sp,
                ols_slope=ols_slope,
                ols_slope_se=ols_se,
                ols_slope_p=ols_p,
                slope_unit=slope_unit,
                best_lag_steps=best_lag,
                best_lag_r=best_r,
                lag_profile=lag_entries,
                compatibility_warnings=compat_warnings,
            )
        )

    # Align response and valid predictors across one common index matrix for partial & OLS.
    reg_summary: MultipleRegressionSummary | None = None
    if len(aligned_vectors) >= 2:
        mat_ts = list(resp_ts)
        resp_aligned = np.array(resp_vals, dtype=np.float64, copy=True)
        for p_name, p_bundle in predictors.items():
            if p_name not in aligned_vectors:
                continue
            mat_ts, resp_aligned, _ = _align_two_series(
                mat_ts, resp_aligned, p_bundle[0], p_bundle[1]
            )

        common_preds: dict[str, NDArray[np.float64]] = {}
        for p_name, p_bundle in predictors.items():
            if p_name not in aligned_vectors:
                continue
            _, _, p_joined = _align_two_series(mat_ts, resp_aligned, p_bundle[0], p_bundle[1])
            common_preds[p_name] = (
                _deseasonalize_by_month(mat_ts, p_joined)
                if cfg.deseasonalize and len(mat_ts) >= 12
                else p_joined
            )
        resp_common = (
            _deseasonalize_by_month(mat_ts, resp_aligned)
            if cfg.deseasonalize and len(mat_ts) >= 12
            else resp_aligned
        )
        reg_summary = _multiple_regression(response_name, resp_common, common_preds)
        if reg_summary is not None:
            all_warnings.extend(reg_summary.warnings)

        # Populate partial correlations controlling for all other predictors.
        updated_pairs: list[CrossVariablePairResult] = []
        for pair in pairwise_results:
            if pair.driver_variable in common_preds and len(common_preds) >= 2:
                other_cols = [
                    vec for name, vec in common_preds.items() if name != pair.driver_variable
                ]
                conf_mat = np.column_stack(other_cols)
                part_r, part_p = compute_partial_correlation(
                    resp_common, common_preds[pair.driver_variable], conf_mat
                )
                pair = pair.model_copy(
                    update={
                        "partial_correlation": float(part_r) if np.isfinite(part_r) else None,
                        "partial_p": float(part_p) if np.isfinite(part_p) else None,
                    }
                )
            updated_pairs.append(pair)
        pairwise_results = updated_pairs

    return CrossVariableResult(
        pairwise=pairwise_results,
        multiple_regression=reg_summary,
        warnings=all_warnings,
    )
