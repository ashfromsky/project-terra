"""Separated uncertainty dimensions (data, statistical, scientific) and sensitivity checks."""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import (
    AutocorrelationPolicy,
    ConfidenceTier,
    DataSourceId,
)
from terra_scientific.domain.models.quality import QualitySummary
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.domain.models.result import (
    SensitivityDiagnostic,
    TrendResult,
    UncertaintySummary,
)
from terra_scientific.sources.catalog import get_source_spec
from terra_scientific.trends.mann_kendall import compute_mann_kendall


def assess_uncertainty_and_sensitivity(
    *,
    sources: list[tuple[DataSourceId, str, QualitySummary]],
    trends: list[TrendResult],
    timestamps: list[datetime] | None = None,
    series_values: NDArray[np.float64] | list[float | None] | None = None,
    trend_config: TrendConfig | None = None,
    has_cross_variable: bool = False,
    interpolation_used: bool = False,
) -> UncertaintySummary:
    """Assess data quality, statistical confidence, and scientific proxy confidence separately."""
    # 1. Data quality tier driven by worst dataset valid fraction and QA coverage.
    if not sources:
        dq_tier = ConfidenceTier.INSUFFICIENT
        dq_rat = "No quantitative datasets passed QA validation."
    else:
        min_cov = min(q.valid_fraction for _, _, q in sources)
        missing_qa_warns = any(
            "no qa flag layers" in w.lower() for _, _, q in sources for w in q.warnings
        )
        nrt_imerg = any(
            "near-real-time" in w.lower() or "early" in w.lower() or "late" in w.lower()
            for _, _, q in sources
            for w in q.warnings
        )
        if min_cov >= 0.85 and not missing_qa_warns and not nrt_imerg and not interpolation_used:
            dq_tier = ConfidenceTier.HIGH
            dq_rat = (
                f"High observation completeness (min valid fraction {min_cov:.2f}) with "
                "official QA flag filtering applied."
            )
        elif min_cov >= 0.60:
            dq_tier = ConfidenceTier.MODERATE
            dq_rat = (
                f"Moderate data completeness (min valid fraction {min_cov:.2f})"
                + ("; missing explicit QA layers." if missing_qa_warns else ".")
                + (" Near-real-time IMERG run used." if nrt_imerg else "")
                + (" Gap interpolation applied." if interpolation_used else "")
            )
        else:
            dq_tier = ConfidenceTier.LOW
            dq_rat = f"Low valid observation coverage ({min_cov:.2f}); high uncertainty from gaps."

    # 2. Statistical confidence tier driven by sample size and serial autocorrelation.
    if not trends:
        stat_tier = ConfidenceTier.UNAVAILABLE
        stat_rat = "No monotonic trend inference executed."
    else:
        min_valid = min(t.valid_count for t in trends)
        has_acf = any(
            t.autocorrelation is not None and t.autocorrelation.significant_autocorrelation
            for t in trends
        )
        adjusted_acf = any(
            t.variant in {"hamed_rao_modified_mk", "prewhiten_yue_wang"} for t in trends
        )
        if min_valid < 8:
            stat_tier = ConfidenceTier.LOW
            stat_rat = f"Small effective sample count (n={min_valid} < 8) limits test power."
        elif has_acf and not adjusted_acf:
            stat_tier = ConfidenceTier.MODERATE
            stat_rat = (
                "Serial autocorrelation detected in detrended residuals while using unadjusted "
                "Mann-Kendall; p-values may overstate confidence."
            )
        elif min_valid >= 20:
            stat_tier = ConfidenceTier.HIGH
            stat_rat = (
                f"Sample size (n={min_valid}) and diagnostic assumptions support "
                "statistical inference."
            )
        else:
            stat_tier = ConfidenceTier.MODERATE
            stat_rat = f"Moderate sample size (n={min_valid}); moderate confidence interval width."

    # 3. Scientific confidence tier capped by physical proxy/scale assumptions.
    limitations: list[str] = []
    seen_lim: set[str] = set()
    for src_id, prod, _ in sources:
        try:
            spec = get_source_spec(src_id, prod)
            for lim in spec.limitations:
                if lim not in seen_lim:
                    seen_lim.add(lim)
                    limitations.append(lim)
        except Exception:
            pass
    if has_cross_variable:
        limitations.append(
            "Cross-variable correlations and regressions quantify statistical co-variation only; "
            "they do not establish physical causality."
        )

    sci_tier = (
        ConfidenceTier.MODERATE
        if dq_tier in {ConfidenceTier.HIGH, ConfidenceTier.MODERATE}
        and stat_tier != ConfidenceTier.LOW
        else ConfidenceTier.LOW
    )
    sci_rat = (
        "Remotely sensed indices and meteorological reanalyses serve as regional environmental "
        "proxies rather than direct ground ecological or causal measurements."
    )

    # Sensitivity check comparing base Mann-Kendall against Hamed-Rao modified MK.
    sens_checks: list[SensitivityDiagnostic] = []
    if timestamps is not None and series_values is not None and trends:
        base_cfg = trend_config or TrendConfig()
        base_t = trends[0]
        if base_cfg.autocorrelation_policy == AutocorrelationPolicy.DIAGNOSTIC_ONLY:
            alt_cfg = base_cfg.model_copy(
                update={"autocorrelation_policy": AutocorrelationPolicy.HAMED_RAO_MODIFIED_MK}
            )
            alt_t = compute_mann_kendall(
                timestamps,
                series_values,
                alt_cfg,
                dataset_id=base_t.dataset_id,
                variable_name=base_t.variable_name,
            )
            rel_p: float | None = None
            if base_t.p_value is not None and alt_t.p_value is not None and base_t.p_value > 1e-12:
                rel_p = (alt_t.p_value - base_t.p_value) / base_t.p_value
            sens_checks.append(
                SensitivityDiagnostic(
                    check_name="Trend p-value sensitivity to Hamed-Rao autocorrelation adjustment",
                    baseline_value=base_t.p_value,
                    alternative_value=alt_t.p_value,
                    relative_difference=rel_p,
                    notes=(
                        f"Direction changed: {base_t.direction.value} -> {alt_t.direction.value}."
                        if base_t.direction != alt_t.direction
                        else "Trend direction remained consistent under autocorrelation adjustment."
                    ),
                )
            )

    return UncertaintySummary(
        data_quality_confidence=dq_tier,
        data_quality_rationale=dq_rat,
        statistical_confidence=stat_tier,
        statistical_rationale=stat_rat,
        scientific_confidence=sci_tier,
        scientific_rationale=sci_rat,
        sensitivity_diagnostics=sens_checks,
        methodological_limitations=limitations,
    )
