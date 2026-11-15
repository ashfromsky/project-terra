"""Scientifically grounded, versioned adaptive thresholds by source, cadence, and method."""

from dataclasses import dataclass

from terra_scientific.domain.enums import (
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    SeasonalGrouping,
    TemporalCadence,
)
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.sources.catalog import get_qa_policy


@dataclass(frozen=True, slots=True)
class SourceReadinessProfile:
    """Physical cadence, expected observation density, and citation metadata for a source."""

    source_id: DataSourceId
    expected_steps_per_year: float
    step_coverage_by_qa: dict[QaPolicyLevel, float]
    earliest_archive_year: int
    citation: str


_PROFILES: dict[DataSourceId, SourceReadinessProfile] = {
    DataSourceId.MODIS_MOD13Q1: SourceReadinessProfile(
        source_id=DataSourceId.MODIS_MOD13Q1,
        expected_steps_per_year=23.0,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.65,
            QaPolicyLevel.STANDARD: 0.50,
            QaPolicyLevel.PERMISSIVE: 0.40,
        },
        earliest_archive_year=2000,
        citation=(
            "MOD13Q1 C6.1 16-day optical composite guide (Didan et al., 2021): "
            "23 composites/yr; 1 valid 16-day composite >= 50% sub-step coverage per month."
        ),
    ),
    DataSourceId.MODIS_MOD11A2: SourceReadinessProfile(
        source_id=DataSourceId.MODIS_MOD11A2,
        expected_steps_per_year=46.0,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.65,
            QaPolicyLevel.STANDARD: 0.50,
            QaPolicyLevel.PERMISSIVE: 0.35,
        },
        earliest_archive_year=2000,
        citation=(
            "MOD11A2 C6.1 8-day clear-sky thermal guide (Wan et al., 2021): "
            "46 composites/yr; thermal masking warrants 50% sub-step coverage under standard QA."
        ),
    ),
    DataSourceId.GPM_IMERG: SourceReadinessProfile(
        source_id=DataSourceId.GPM_IMERG,
        expected_steps_per_year=365.25 * 48.0,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.65,
            QaPolicyLevel.STANDARD: 0.50,
            QaPolicyLevel.PERMISSIVE: 0.35,
        },
        earliest_archive_year=2000,
        citation=(
            "GPM IMERG V07 half-hourly precipitation ATBD (Huffman et al., 2023): "
            "intermittent half-hourly rate-to-depth integration allows 50% standard PQI coverage."
        ),
    ),
    DataSourceId.SMAP_SPL3SMP_E: SourceReadinessProfile(
        source_id=DataSourceId.SMAP_SPL3SMP_E,
        expected_steps_per_year=182.0,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.60,
            QaPolicyLevel.STANDARD: 0.40,
            QaPolicyLevel.PERMISSIVE: 0.30,
        },
        earliest_archive_year=2015,
        citation=(
            "SMAP SPL3SMP_E V006 User Guide (O'Neill et al., 2023): 2-3 day orbital revisit "
            "with RFI/freeze masking requires >= 40% target-bin coverage under standard QA."
        ),
    ),
    DataSourceId.NASA_POWER: SourceReadinessProfile(
        source_id=DataSourceId.NASA_POWER,
        expected_steps_per_year=365.25,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.85,
            QaPolicyLevel.STANDARD: 0.70,
            QaPolicyLevel.PERMISSIVE: 0.55,
        },
        earliest_archive_year=1981,
        citation=(
            "NASA POWER MERRA-2 / CERES assimilated daily meteorology: spatially continuous "
            "reanalysis expects >= 70% daily completeness per aggregated period."
        ),
    ),
    DataSourceId.CUSTOM: SourceReadinessProfile(
        source_id=DataSourceId.CUSTOM,
        expected_steps_per_year=12.0,
        step_coverage_by_qa={
            QaPolicyLevel.STRICT: 0.75,
            QaPolicyLevel.STANDARD: 0.60,
            QaPolicyLevel.PERMISSIVE: 0.45,
        },
        earliest_archive_year=1970,
        citation="Default scientific series policy requiring >= 60% sub-period validity.",
    ),
}


def get_source_readiness_profile(source_id: DataSourceId) -> SourceReadinessProfile:
    """Return the versioned readiness profile for a dataset source."""
    return _PROFILES.get(source_id, _PROFILES[DataSourceId.CUSTOM])


def resolve_qa_sufficiency_threshold(
    source_id: DataSourceId,
    product: str,
    qa_level: QaPolicyLevel,
) -> tuple[float, str]:
    """Return source- and QA-policy-specific valid observation fraction floor and rationale."""
    profile = get_source_readiness_profile(source_id)
    try:
        policy = get_qa_policy(source_id, product, qa_level)
        return (
            float(policy.min_coverage_fraction),
            f"{policy.description}. Source policy '{policy.policy_id}' requires "
            f">= {policy.min_coverage_fraction:.0%} valid observations. ({profile.citation})",
        )
    except ScientificInputError:
        threshold = profile.step_coverage_by_qa.get(qa_level, 0.55)
        return (
            threshold,
            f"Source profile fallback under '{qa_level.value}' QA requires >= {threshold:.0%}. "
            f"({profile.citation})",
        )


def resolve_aggregation_min_coverage(
    source_id: DataSourceId,
    raw_cadence: TemporalCadence,
    target_cadence: TemporalCadence,
    qa_level: QaPolicyLevel,
) -> tuple[float, str]:
    """Derive sub-step coverage floor per target temporal bin without uniform hardcoding."""
    profile = get_source_readiness_profile(source_id)
    if raw_cadence == target_cadence:
        return (
            0.5,
            "Native cadence matches target cadence (single step/bin); valid step retained.",
        )
    if target_cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}:
        return (
            0.5,
            "Target composite cadence preserves native composite timestamps directly.",
        )
    floor = profile.step_coverage_by_qa.get(qa_level, 0.60)
    return (
        floor,
        f"Aggregating {raw_cadence.value} -> {target_cadence.value} requires >= {floor:.0%} valid "
        f"sub-steps per bin under '{qa_level.value}' QA. {profile.citation}",
    )


def resolve_trend_requirements(
    target_cadence: TemporalCadence,
    trend_config: TrendConfig,
) -> tuple[int, int, str]:
    """Return (min_required_steps, recommended_asymptotic_steps, rationale)."""
    recommended = 10
    if "min_samples" in trend_config.model_fields_set:
        min_req = max(4, trend_config.min_samples)
        return (
            min_req,
            max(recommended, min_req),
            f"Caller-configured trend floor min_samples={min_req}; asymptotic normal "
            "approximation stabilizes at n >= 10 (Kendall, 1975).",
        )

    if target_cadence == TemporalCadence.ANNUAL:
        min_req = 4
        rationale = (
            "Annual trend series uses exact small-n Mann-Kendall permutation down to n >= 4 years; "
            "normal approximation requires n >= 10 years."
        )
    elif target_cadence == TemporalCadence.DAILY:
        min_req = max(10, trend_config.min_samples)
        recommended = 30
        rationale = (
            "Daily series exhibits high synoptic autocorrelation; >= 10 observations required "
            "(>= 30 recommended) to prevent short-term weather aliasing."
        )
    else:
        min_req = max(6, trend_config.min_samples)
        rationale = (
            f"{target_cadence.value} Mann-Kendall & Sen's slope require >= {min_req} valid steps "
            "(exact permutation valid for 4 <= n < 10; asymptotic p-values reliable at n >= 10)."
        )
    return min_req, recommended, rationale


def resolve_baseline_requirements(
    *,
    baseline_type: BaselineType,
    seasonal_grouping: SeasonalGrouping,
    explicit_min_years: int | None = None,
    explicit_min_samples_per_bin: int | None = None,
) -> tuple[int, int, str]:
    """Return (min_years_required, min_samples_per_bin, scientific_rationale)."""
    min_years = explicit_min_years if explicit_min_years is not None else 3
    min_samples = explicit_min_samples_per_bin if explicit_min_samples_per_bin is not None else 3
    grouping_note = (
        "12 calendar-month strata"
        if seasonal_grouping == SeasonalGrouping.CALENDAR_MONTH
        else (
            "4 quarterly seasons"
            if seasonal_grouping == SeasonalGrouping.QUARTERLY
            else f"{seasonal_grouping.value} strata"
        )
    )
    if baseline_type == BaselineType.FIXED_REFERENCE:
        rationale = (
            f"Fixed reference climatology ({grouping_note}) requires >= {min_years} distinct "
            f"reference years and >= {min_samples} samples/bin prior to assessment overlap."
        )
    elif baseline_type == BaselineType.OUT_OF_SAMPLE:
        rationale = (
            f"Out-of-sample baseline ({grouping_note}) requires >= {min_years} distinct "
            f"non-assessment years and >= {min_samples} samples/bin."
        )
    else:
        rationale = (
            f"In-sample baseline ({grouping_note}) requires >= {min_years} distinct years "
            f"and >= {min_samples} samples/bin for within-stratum variance/MAD; fewer years "
            "confound inter-annual anomalies."
        )
    return min_years, min_samples, rationale
