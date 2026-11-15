"""Unit tests for cross-variable associations, deseasonalization, regression, and guards."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from terra_scientific.cross_variable.analysis import (
    analyze_cross_variables,
    compute_partial_correlation,
)
from terra_scientific.domain.enums import DataSourceId, VariableSemanticKind
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.dataset import VariableMetadata
from terra_scientific.domain.models.request import CrossVariableConfig


def test_lagged_deseasonalized_correlation_detects_one_step_precipitation_lag() -> None:
    rng = np.random.default_rng(7)
    n = 60
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=30 * i) for i in range(n)]
    months = np.array([d.month for d in ts])
    season = 0.2 * np.sin(2.0 * np.pi * (months - 1) / 12.0)

    precip_anom = rng.normal(0.0, 20.0, size=n)
    precip = 80.0 + 30.0 * np.sin(2.0 * np.pi * (months - 1) / 12.0) + precip_anom

    ndvi_anom = np.zeros(n)
    ndvi_anom[1:] = 0.004 * precip_anom[:-1] + rng.normal(0.0, 0.01, size=n - 1)
    ndvi = 0.5 + season + ndvi_anom

    meta_ndvi = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    meta_precip = VariableMetadata(
        name="precipitation",
        canonical_name="precipitation_depth",
        units="mm",
        semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
    )

    result = analyze_cross_variables(
        response_name="NDVI",
        response_series=(ts, ndvi, meta_ndvi, DataSourceId.MODIS_MOD13Q1, 250.0),
        predictors={"precipitation": (ts, precip, meta_precip, DataSourceId.GPM_IMERG, 11132.0)},
        config=CrossVariableConfig(max_lag_steps=4, deseasonalize=True),
    )
    pair = result.pairwise[0]
    assert pair.best_lag_steps == 1
    assert pair.best_lag_r is not None and pair.best_lag_r > 0.7
    assert "causality" in pair.non_causal_notice.lower()
    # Spatial support ratio 11132 / 250 > 40x must emit compatibility warning
    assert any(
        "spatial" in w.lower() or "resolution" in w.lower() for w in pair.compatibility_warnings
    )


def test_power_precip_with_gpm_imerg_blocked_unless_explicit() -> None:
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(12)]
    meta_gpm = VariableMetadata(
        name="Grid/precipitation",
        canonical_name="precipitation_depth",
        units="mm",
        semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
    )
    meta_pow = VariableMetadata(
        name="PRECTOTCORR",
        canonical_name="bias_corrected_precipitation",
        units="mm/day",
        semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
    )
    vals = np.linspace(10.0, 50.0, 12)
    with pytest.raises(ScientificInputError, match="PRECTOTCORR"):
        analyze_cross_variables(
            response_name="Grid/precipitation",
            response_series=(ts, vals, meta_gpm, DataSourceId.GPM_IMERG, 11132.0),
            predictors={"PRECTOTCORR": (ts, vals, meta_pow, DataSourceId.NASA_POWER, 55000.0)},
            config=CrossVariableConfig(allow_power_precip_with_gpm=False),
        )


def test_partial_correlation_and_multiple_regression() -> None:
    rng = np.random.default_rng(11)
    n = 50
    confounder = rng.normal(size=n)
    x1 = 0.8 * confounder + rng.normal(scale=0.5, size=n)
    x2 = rng.normal(size=n)
    y = 2.0 * x1 - 1.5 * x2 + 0.5 * confounder + rng.normal(scale=0.1, size=n)

    pr, pp = compute_partial_correlation(y, x1, np.column_stack([confounder, x2]))
    assert pr > 0.95
    assert pp < 1e-6

    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]
    m_y = VariableMetadata(
        name="y",
        canonical_name="y",
        units="u",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    m_x1 = VariableMetadata(
        name="x1",
        canonical_name="x1",
        units="u",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    m_x2 = VariableMetadata(
        name="x2",
        canonical_name="x2",
        units="u",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    res = analyze_cross_variables(
        response_name="y",
        response_series=(ts, y, m_y, DataSourceId.CUSTOM, 1000.0),
        predictors={
            "x1": (ts, x1, m_x1, DataSourceId.CUSTOM, 1000.0),
            "x2": (ts, x2, m_x2, DataSourceId.CUSTOM, 1000.0),
        },
        config=CrossVariableConfig(deseasonalize=False, max_lag_steps=0),
    )
    assert res.multiple_regression is not None
    assert res.multiple_regression.r_squared is not None
    assert res.multiple_regression.r_squared > 0.9
    assert res.multiple_regression.coefficients["x1"] > 1.5
    assert res.multiple_regression.coefficients["x2"] < -1.0

    # Verify pairwise OLS slope preserves response/driver units rather than Pearson r.
    m_ndvi = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    m_precip = VariableMetadata(
        name="precip",
        canonical_name="precipitation",
        units="mm/month",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    x_precip = np.linspace(10.0, 200.0, 24)
    y_ndvi = 0.0025 * x_precip + 0.1  # exact OLS slope = 0.0025 (dimensionless / (mm/month))
    ts_m = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(24)]
    pair_res = analyze_cross_variables(
        response_name="ndvi",
        response_series=(ts_m, y_ndvi, m_ndvi, DataSourceId.CUSTOM, 1000.0),
        predictors={"precip": (ts_m, x_precip, m_precip, DataSourceId.CUSTOM, 1000.0)},
        config=CrossVariableConfig(deseasonalize=False, max_lag_steps=0),
    )
    assert len(pair_res.pairwise) == 1
    p0 = pair_res.pairwise[0]
    assert p0.pearson_r == pytest.approx(1.0)
    assert p0.ols_slope == pytest.approx(0.0025)
    assert p0.ols_slope != pytest.approx(p0.pearson_r)
    assert p0.slope_unit == "dimensionless/mm/month"
    assert p0.ols_slope_se is not None
    assert p0.ols_slope_p is not None and p0.ols_slope_p < 1e-6
