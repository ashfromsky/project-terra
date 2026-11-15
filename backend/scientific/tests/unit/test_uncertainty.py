"""Unit tests for separated 3-tier uncertainty reporting and robustness sensitivity checks."""

from datetime import UTC, datetime, timedelta

import numpy as np

from terra_scientific.domain.enums import (
    ConfidenceTier,
    DataSourceId,
    TrendDirection,
)
from terra_scientific.domain.models.quality import QualitySummary
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.domain.models.result import AutocorrelationDiagnostics, TrendResult
from terra_scientific.uncertainty.assessor import (
    assess_uncertainty_and_sensitivity,
)


def test_uncertainty_distinguishes_data_quality_statistical_and_scientific_tiers() -> None:
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(24)]
    vals = np.linspace(0.4, 0.6, 24) + 0.02 * np.sin(np.arange(24))

    q_summary = QualitySummary(
        total_observations=24,
        valid_observations=24,
        valid_fraction=1.0,
        qa_policy_applied="mod13q1_standard_v61",
        passed_sufficiency=True,
    )
    trend = TrendResult(
        dataset_id="mod13",
        variable_name="NDVI",
        variant="standard_mk",
        sample_count=24,
        valid_count=24,
        direction=TrendDirection.INCREASING,
        p_value=0.001,
        sens_slope=0.10,
        slope_unit="dimensionless/year",
        autocorrelation=AutocorrelationDiagnostics(
            lag1_acf=0.6,
            significant_autocorrelation=True,
            effective_sample_size=8.0,
            policy_applied="diagnostic_only",
        ),
    )

    unc = assess_uncertainty_and_sensitivity(
        sources=[(DataSourceId.MODIS_MOD13Q1, "MOD13Q1.061", q_summary)],
        trends=[trend],
        timestamps=ts,
        series_values=vals,
        trend_config=TrendConfig(),
        has_cross_variable=False,
    )
    # High data coverage (100%), yet statistical confidence downgraded by autocorrelation,
    # and scientific confidence explicitly bounded by proxy nature of NDVI.
    assert unc.data_quality_confidence == ConfidenceTier.HIGH
    assert unc.statistical_confidence == ConfidenceTier.MODERATE
    assert unc.scientific_confidence == ConfidenceTier.MODERATE
    assert len(unc.sensitivity_diagnostics) >= 1
    assert any("autocorrelation" in d.check_name.lower() for d in unc.sensitivity_diagnostics)
    assert any(
        "spectral" in lim.lower() or "ndvi" in lim.lower() for lim in unc.methodological_limitations
    )
