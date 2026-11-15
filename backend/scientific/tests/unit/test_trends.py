"""Unit tests for Mann-Kendall, Seasonal MK, Sen's slope, and autocorrelation."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from terra_scientific.domain.enums import (
    AutocorrelationPolicy,
    SeasonalGrouping,
    TrendDirection,
)
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.trends.mann_kendall import compute_mann_kendall
from terra_scientific.trends.seasonal_mk import compute_seasonal_mann_kendall
from terra_scientific.trends.sens_slope import compute_sens_slope


def test_mann_kendall_detects_increasing_decreasing_and_no_trend() -> None:
    ts = [datetime(2010 + i, 1, 1, tzinfo=UTC) for i in range(15)]
    inc = np.linspace(0.2, 0.8, 15)
    res_inc = compute_mann_kendall(ts, inc, TrendConfig(min_samples=6))
    assert res_inc.direction == TrendDirection.INCREASING
    assert res_inc.p_value is not None and res_inc.p_value < 1e-4
    assert res_inc.kendalls_tau == pytest.approx(1.0)
    assert res_inc.sens_slope is not None and res_inc.sens_slope > 0.03

    dec = np.linspace(0.8, 0.2, 15)
    res_dec = compute_mann_kendall(ts, dec, TrendConfig(min_samples=6))
    assert res_dec.direction == TrendDirection.DECREASING
    assert res_dec.p_value is not None and res_dec.p_value < 1e-4
    assert res_dec.sens_slope is not None and res_dec.sens_slope < -0.03

    flat_alt = np.array([0.5, 0.6, 0.5, 0.6, 0.5, 0.6, 0.5, 0.6, 0.5, 0.6, 0.5, 0.6])
    res_flat = compute_mann_kendall(ts[:12], flat_alt, TrendConfig(min_samples=6))
    assert res_flat.direction == TrendDirection.NO_TREND
    assert res_flat.p_value is not None and res_flat.p_value > 0.2


def test_mann_kendall_small_sample_uses_exact_distribution_and_insufficient_guard() -> None:
    # Gilbert (1987) Table A18: for n=4, S=6 yields exact two-sided p = 2/24 = 0.083333.
    ts4 = [datetime(2020 + i, 1, 1, tzinfo=UTC) for i in range(4)]
    res4 = compute_mann_kendall(ts4, np.array([1.0, 2.0, 3.0, 4.0]), TrendConfig(min_samples=4))
    assert res4.s_statistic == pytest.approx(6.0)
    assert res4.p_value == pytest.approx(2.0 / 24.0, abs=1e-6)
    assert res4.direction == TrendDirection.NO_TREND  # Not significant at alpha=0.05!

    # Insufficient valid samples due to NaNs
    sparse = np.array([1.0, np.nan, np.nan, 2.0])
    res_insuff = compute_mann_kendall(ts4, sparse, TrendConfig(min_samples=4))
    assert res_insuff.direction == TrendDirection.INSUFFICIENT_DATA
    assert res_insuff.p_value is None


def test_sens_slope_uses_actual_elapsed_time_and_handles_duplicates_and_outliers() -> None:
    # Exact +0.02 per year despite irregular gaps and an outlier at index 4
    base = datetime(2015, 1, 1, tzinfo=UTC)
    days = [0, 365, 731, 1461, 1826, 2192, 2557, 2922, 3287]
    ts = [base + timedelta(days=d) for d in days]
    elapsed_yrs = np.array([d / 365.25 for d in days])
    vals = 0.3 + 0.02 * elapsed_yrs
    vals[4] = 9.9  # Single large outlier must not corrupt Sen's median slope

    slope_res = compute_sens_slope(ts, vals, unit_label="NDVI", time_unit="year")
    assert slope_res.slope == pytest.approx(0.02, abs=1e-3)
    assert slope_res.ci_low is not None and slope_res.ci_high is not None
    assert slope_res.ci_low <= slope_res.slope <= slope_res.ci_high

    # Duplicate timestamps ignored cleanly without ZeroDivisionError
    dup_ts = [ts[0], ts[0], ts[1], ts[2], ts[3], ts[4]]
    dup_vals = np.array([0.3, 0.31, 0.32, 0.34, 0.38, 0.40])
    dup_slope = compute_sens_slope(dup_ts, dup_vals, time_unit="year")
    assert np.isfinite(dup_slope.slope)


def test_seasonal_mann_kendall_detects_trend_under_strong_seasonality() -> None:
    ts: list[datetime] = []
    vals: list[float] = []
    for yr in range(2015, 2025):
        for month in range(1, 13):
            ts.append(datetime(yr, month, 1, tzinfo=UTC))
            seasonal_cycle = 0.25 * np.sin(2.0 * np.pi * (month - 1) / 12.0)
            trend = 0.015 * (yr - 2015)
            vals.append(float(0.5 + seasonal_cycle + trend))

    res = compute_seasonal_mann_kendall(
        ts,
        np.array(vals),
        TrendConfig(seasonal_grouping=SeasonalGrouping.CALENDAR_MONTH),
    )
    assert res.overall_direction == TrendDirection.INCREASING
    assert res.p_value is not None and res.p_value < 1e-6
    assert res.seasonal_sens_slope == pytest.approx(0.015, abs=1e-3)
    assert len(res.season_results) == 12


def test_autocorrelation_diagnostics_hamed_rao_and_tfpw_modes() -> None:
    rng = np.random.default_rng(42)
    n = 60
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(n)]
    # Generate strongly autocorrelated AR(1) noise without deterministic trend (phi = 0.85)
    ar1 = np.zeros(n)
    for i in range(1, n):
        ar1[i] = 0.85 * ar1[i - 1] + rng.normal(0.0, 0.2)

    diag_only = compute_mann_kendall(
        ts, ar1, TrendConfig(autocorrelation_policy=AutocorrelationPolicy.DIAGNOSTIC_ONLY)
    )
    assert diag_only.autocorrelation is not None
    assert diag_only.autocorrelation.lag1_acf is not None
    assert diag_only.autocorrelation.lag1_acf > 0.5
    assert diag_only.autocorrelation.significant_autocorrelation is True
    assert diag_only.autocorrelation.effective_sample_size is not None
    assert diag_only.autocorrelation.effective_sample_size < n

    hr = compute_mann_kendall(
        ts, ar1, TrendConfig(autocorrelation_policy=AutocorrelationPolicy.HAMED_RAO_MODIFIED_MK)
    )
    assert hr.var_s is not None and diag_only.var_s is not None
    # Positive autocorrelation inflates Var(S) under Hamed-Rao correction -> larger p-value
    assert hr.var_s > diag_only.var_s
    assert hr.p_value is not None and diag_only.p_value is not None
    assert hr.p_value >= diag_only.p_value

    tfpw = compute_mann_kendall(
        ts, ar1, TrendConfig(autocorrelation_policy=AutocorrelationPolicy.PREWHITEN_YUE_WANG)
    )
    assert "prewhiten" in tfpw.variant.lower()
