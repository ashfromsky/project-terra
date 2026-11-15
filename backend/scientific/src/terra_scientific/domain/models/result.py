"""Typed scientific result models across all P0 and P1 analytical stages."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import (
    AggregationOperator,
    AssessmentStatus,
    ConfidenceTier,
    PriorityTier,
    StageStatus,
    TemporalCadence,
    TrendDirection,
)
from terra_scientific.domain.models.provenance import ProvenanceTrace
from terra_scientific.domain.models.quality import QualitySummary
from terra_scientific.domain.models.readiness import ReadinessAssessmentReport
from terra_scientific.domain.models.request import AssessmentRequest


class TemporalSeriesResult(BaseModel):
    """Temporally aggregated variable series with interval coverage provenance."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    units: str
    cadence: TemporalCadence
    aggregation_operator: AggregationOperator
    timestamps: list[datetime]
    values: list[float | None]
    expected_subintervals: list[int] = Field(default_factory=list)
    valid_subintervals: list[int] = Field(default_factory=list)
    coverage_fractions: list[float] = Field(default_factory=list)
    interpolation_applied: bool = False
    interpolated_indices: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClimatologyBin(BaseModel):
    """Reference statistics for one seasonal bin (calendar month or DOY bin)."""

    model_config = ConfigDict(frozen=True)

    bin_key: int
    bin_label: str
    sample_count: int
    mean: float | None
    median: float | None
    std: float | None
    mad: float | None
    iqr: float | None
    q10: float | None
    q90: float | None


class BaselineClimatologyResult(BaseModel):
    """Reference baseline climatology across seasonal strata."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    units: str
    baseline_type: str
    reference_start: datetime
    reference_end: datetime
    seasonal_grouping: str
    bins: list[ClimatologyBin] = Field(default_factory=list)
    sufficient: bool
    warnings: list[str] = Field(default_factory=list)


class PersistentAnomalyRun(BaseModel):
    """Consecutive sequence of extreme or persistent threshold anomalies."""

    model_config = ConfigDict(frozen=True)

    start_timestamp: datetime
    end_timestamp: datetime
    step_count: int
    polarity: str
    peak_zscore: float
    mean_zscore: float
    cumulative_departure: float


class AnomalyResult(BaseModel):
    """Standardized, robust, and percentile anomalies relative to climatology."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    units: str
    timestamps: list[datetime]
    raw_anomalies: list[float | None]
    standard_zscores: list[float | None]
    robust_zscores: list[float | None]
    percentiles: list[float | None]
    persistent_runs: list[PersistentAnomalyRun] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AutocorrelationDiagnostics(BaseModel):
    """Serial correlation diagnostics informing trend significance caution."""

    model_config = ConfigDict(frozen=True)

    lag1_acf: float | None
    acf_values: list[float | None] = Field(default_factory=list)
    ljung_box_stat: float | None = None
    ljung_box_p: float | None = None
    effective_sample_size: float | None = None
    significant_autocorrelation: bool = False
    policy_applied: str


class TrendResult(BaseModel):
    """Non-parametric monotonic trend and Sen's slope inference result."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    variant: str
    sample_count: int
    valid_count: int
    direction: TrendDirection
    s_statistic: float | None = None
    var_s: float | None = None
    z_statistic: float | None = None
    p_value: float | None = None
    adjusted_p_value: float | None = None
    kendalls_tau: float | None = None
    sens_slope: float | None = None
    slope_unit: str = ""
    sens_intercept: float | None = None
    slope_ci_low: float | None = None
    slope_ci_high: float | None = None
    alpha: float = 0.05
    autocorrelation: AutocorrelationDiagnostics | None = None
    warnings: list[str] = Field(default_factory=list)


class SeasonalGroupTrend(BaseModel):
    """Per-season stratum contribution to Seasonal Mann-Kendall."""

    model_config = ConfigDict(frozen=True)

    season_key: int
    season_label: str
    sample_count: int
    s_statistic: float
    var_s: float
    sens_slope: float | None = None


class SeasonalTrendResult(BaseModel):
    """Hirsch-Slack Seasonal Mann-Kendall & seasonal Sen's slope outcome."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    grouping_mode: str
    overall_direction: TrendDirection
    total_s: float | None = None
    total_var_s: float | None = None
    z_statistic: float | None = None
    p_value: float | None = None
    seasonal_sens_slope: float | None = None
    slope_unit: str = ""
    season_results: list[SeasonalGroupTrend] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpatialStatsResult(BaseModel):
    """P0 zonal statistics + P1 spatial autocorrelation and pixel trend summaries."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    units: str
    crs: str
    area_weighted_mean: float | None
    unweighted_mean: float | None
    median: float | None
    std: float | None
    iqr: float | None
    q10: float | None
    q25: float | None
    q75: float | None
    q90: float | None
    valid_pixel_count: int
    total_pixel_count: int
    coverage_fraction: float
    morans_i: float | None = None
    morans_z: float | None = None
    morans_p_value: float | None = None
    hotspot_significant_fraction: float | None = None
    coldspot_significant_fraction: float | None = None
    pixel_trend_significant_fdr_fraction: float | None = None
    pixel_trend_positive_fraction: float | None = None
    pixel_trend_negative_fraction: float | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class LagCorrelationEntry(BaseModel):
    """Cross-correlation statistics at one integer cadence lag."""

    model_config = ConfigDict(frozen=True)

    lag_steps: int
    sample_count: int
    pearson_r: float | None
    pearson_p: float | None
    spearman_rho: float | None
    spearman_p: float | None


class CrossVariablePairResult(BaseModel):
    """Pairwise statistical association metrics between two variables."""

    model_config = ConfigDict(frozen=True)

    response_variable: str
    driver_variable: str
    deseasonalized: bool
    overlap_count: int
    pearson_r: float | None
    pearson_p: float | None
    pearson_ci_low: float | None = None
    pearson_ci_high: float | None = None
    spearman_rho: float | None
    spearman_p: float | None
    ols_slope: float | None = None
    ols_slope_se: float | None = None
    ols_slope_p: float | None = None
    slope_unit: str = ""
    partial_correlation: float | None = None
    partial_p: float | None = None
    best_lag_steps: int | None = None
    best_lag_r: float | None = None
    lag_profile: list[LagCorrelationEntry] = Field(default_factory=list)
    compatibility_warnings: list[str] = Field(default_factory=list)
    non_causal_notice: str = (
        "Statistical association only; correlation or lagged cross-correlation does not "
        "establish physical causality."
    )


class MultipleRegressionSummary(BaseModel):
    """OLS multivariate sensitivity association summary across compatible predictors."""

    model_config = ConfigDict(frozen=True)

    response_variable: str
    predictor_variables: list[str]
    sample_count: int
    r_squared: float | None
    adjusted_r_squared: float | None
    coefficients: dict[str, float] = Field(default_factory=dict)
    standard_errors: dict[str, float] = Field(default_factory=dict)
    p_values: dict[str, float] = Field(default_factory=dict)
    vif: dict[str, float] = Field(default_factory=dict)
    non_causal_notice: str = (
        "Regression slopes represent statistical co-variation under linear assumptions, "
        "not causal attribution."
    )
    warnings: list[str] = Field(default_factory=list)


class CrossVariableResult(BaseModel):
    """Cross-variable analysis output container."""

    model_config = ConfigDict(frozen=True)

    pairwise: list[CrossVariablePairResult] = Field(default_factory=list)
    multiple_regression: MultipleRegressionSummary | None = None
    warnings: list[str] = Field(default_factory=list)


class ChangePointEntry(BaseModel):
    """Detected statistical structural break without invented causal label."""

    model_config = ConfigDict(frozen=True)

    method: str
    timestamp: datetime
    index: int
    statistic: float
    p_value: float | None
    mean_before: float
    mean_after: float
    shift_magnitude: float
    classification: str = "statistical_change_point"
    cause_attribution_status: str = "not_determined_without_external_evidence"


class DisturbanceResult(BaseModel):
    """Statistical change-points and candidate anomaly disturbance episodes."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    change_points: list[ChangePointEntry] = Field(default_factory=list)
    candidate_disturbance_runs: list[PersistentAnomalyRun] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecoveryEventResult(BaseModel):
    """Event-centered post-anomaly trajectory evaluation."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    event_start: datetime
    event_peak_timestamp: datetime
    observation_end: datetime
    pre_event_baseline: float
    event_minimum_or_peak: float
    deficit_magnitude: float
    elapsed_recovery_rate: float | None = None
    rate_unit: str = ""
    time_to_recovery_days: float | None = None
    recovery_completeness: float
    post_event_residual: float | None = None
    status: str
    deseasonalized_series_used: bool
    seasonal_caveat: str
    warnings: list[str] = Field(default_factory=list)


class EventResistanceDetail(BaseModel):
    """Per-event resistance traceability from a negative disturbance peak."""

    model_config = ConfigDict(frozen=True)

    event_start: datetime
    event_end: datetime | None = None
    event_peak_timestamp: datetime | None = None
    peak_negative_zscore: float
    resistance: float


class ResilienceMetricValue(BaseModel):
    """Single interpretable resilience dimension with explicit formula and status."""

    model_config = ConfigDict(frozen=True)

    dimension: str
    available: bool
    status: StageStatus
    value: float | None = None
    unit: str = ""
    formula: str
    interpretation: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    event_values: list[EventResistanceDetail] = Field(default_factory=list)


class CompositeTriStatus(BaseModel):
    """Explicit placeholder refusing unvalidated composite TRI weights."""

    model_config = ConfigDict(frozen=True)

    status: str = "unavailable_unvalidated"
    value: None = None
    reason: str = (
        "Composite TERRA Resilience Index (TRI) is intentionally withheld until domain-validated "
        "weights and calibration benchmarks are approved."
    )


class ResilienceMetricsResult(BaseModel):
    """Separated measurable resilience dimensions without unvalidated composite scoring."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    variable_name: str
    resistance: ResilienceMetricValue
    recovery: ResilienceMetricValue
    stability: ResilienceMetricValue
    sensitivity: ResilienceMetricValue
    composite_tri: CompositeTriStatus = Field(default_factory=CompositeTriStatus)


class SensitivityDiagnostic(BaseModel):
    """Robustness check measuring output change under alternative method parameters."""

    model_config = ConfigDict(frozen=True)

    check_name: str
    baseline_value: float | None
    alternative_value: float | None
    relative_difference: float | None
    notes: str


class UncertaintySummary(BaseModel):
    """Explicitly separated Data Quality, Statistical Confidence, and Scientific Confidence."""

    model_config = ConfigDict(frozen=True)

    data_quality_confidence: ConfidenceTier
    data_quality_rationale: str
    statistical_confidence: ConfidenceTier
    statistical_rationale: str
    scientific_confidence: ConfidenceTier
    scientific_rationale: str
    sensitivity_diagnostics: list[SensitivityDiagnostic] = Field(default_factory=list)
    methodological_limitations: list[str] = Field(default_factory=list)


class StageExecutionReport(BaseModel):
    """Execution telemetry and status tracking per pipeline stage."""

    model_config = ConfigDict(frozen=True)

    stage_name: str
    priority: PriorityTier
    status: StageStatus
    duration_ms: float = Field(ge=0.0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    skip_reason: str | None = None


class ScientificAssessmentResult(BaseModel):
    """Top-level traceable and reproducible Scientific Assessment deliverable."""

    model_config = ConfigDict(frozen=True)

    assessment_id: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request: AssessmentRequest
    status: AssessmentStatus
    quality_reports: dict[str, QualitySummary] = Field(default_factory=dict)
    temporal_series: list[TemporalSeriesResult] = Field(default_factory=list)
    baselines: list[BaselineClimatologyResult] = Field(default_factory=list)
    anomalies: list[AnomalyResult] = Field(default_factory=list)
    trends: list[TrendResult] = Field(default_factory=list)
    seasonal_trends: list[SeasonalTrendResult] = Field(default_factory=list)
    spatial_stats: list[SpatialStatsResult] = Field(default_factory=list)
    cross_variable: CrossVariableResult | None = None
    disturbances: list[DisturbanceResult] = Field(default_factory=list)
    recoveries: list[RecoveryEventResult] = Field(default_factory=list)
    resilience: list[ResilienceMetricsResult] = Field(default_factory=list)
    uncertainty: UncertaintySummary | None = None
    readiness: ReadinessAssessmentReport | None = None
    stages: list[StageExecutionReport] = Field(default_factory=list)
    provenance: ProvenanceTrace | None = None
    artifact_manifest: dict[str, str] = Field(default_factory=dict)
    summary_warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
