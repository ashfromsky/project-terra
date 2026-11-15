"""Assessment request and stage-level configuration contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from terra_scientific.domain.enums import (
    AggregationOperator,
    AutocorrelationPolicy,
    BaselineType,
    OverpassMode,
    QaPolicyLevel,
    SeasonalGrouping,
    TemporalCadence,
)
from terra_scientific.domain.models.temporal import ensure_utc


class BaselineConfig(BaseModel):
    """Baseline & climatology calculation parameters."""

    model_config = ConfigDict(frozen=True)

    baseline_type: BaselineType = BaselineType.FIXED_REFERENCE
    start: datetime | None = None
    end: datetime | None = None
    seasonal_grouping: SeasonalGrouping = SeasonalGrouping.CALENDAR_MONTH
    min_years_required: int = Field(default=3, ge=1)
    min_samples_per_bin: int = Field(default=3, ge=1)
    exclude_assessment_overlap: bool = True
    allow_explicit_full_period: bool = False

    @model_validator(mode="after")
    def _validate_dates(self) -> "BaselineConfig":
        if self.start is not None:
            object.__setattr__(self, "start", ensure_utc(self.start))
        if self.end is not None:
            object.__setattr__(self, "end", ensure_utc(self.end))
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("Baseline end must be >= baseline start")
        if (
            self.baseline_type == BaselineType.FULL_PERIOD_EXPLICIT
            and not self.allow_explicit_full_period
        ):
            raise ValueError(
                "FULL_PERIOD_EXPLICIT requires allow_explicit_full_period=True to avoid "
                "accidental baseline data leakage"
            )
        return self


class AnomalyConfig(BaseModel):
    """Anomaly detection configuration."""

    model_config = ConfigDict(frozen=True)

    zscore_threshold: float = Field(default=1.5, gt=0.0)
    extreme_zscore_threshold: float = Field(default=2.0, gt=0.0)
    min_persistence_steps: int = Field(default=2, ge=1)
    use_robust_default: bool = True


class TrendConfig(BaseModel):
    """Monotonic trend & autocorrelation inference settings."""

    model_config = ConfigDict(frozen=True)

    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    min_samples: int = Field(default=6, ge=4)
    slope_time_unit: str = "year"
    seasonal_grouping: SeasonalGrouping = SeasonalGrouping.CALENDAR_MONTH
    autocorrelation_policy: AutocorrelationPolicy = AutocorrelationPolicy.DIAGNOSTIC_ONLY
    max_acf_lag: int = Field(default=12, ge=1)
    apply_fdr_for_pixels: bool = True


class SpatialConfig(BaseModel):
    """Spatial aggregation and local autocorrelation parameters."""

    model_config = ConfigDict(frozen=True)

    area_weighted: bool = True
    compute_pixel_trends: bool = True
    compute_autocorrelation: bool = True
    knn_neighbors: int = Field(default=8, ge=2, le=64)
    permutations: int = Field(default=199, ge=0, le=9999)
    chunk_rows: int = Field(default=128, ge=1)
    min_pixel_coverage: float = Field(default=0.5, gt=0.0, le=1.0)


class CrossVariableConfig(BaseModel):
    """Cross-variable statistical association settings."""

    model_config = ConfigDict(frozen=True)

    max_lag_steps: int = Field(default=6, ge=0, le=36)
    min_overlap_samples: int = Field(default=8, ge=4)
    deseasonalize: bool = True
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    allow_power_precip_with_gpm: bool = False


class DisturbanceConfig(BaseModel):
    """Statistical change-point and anomaly-event detection settings."""

    model_config = ConfigDict(frozen=True)

    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    min_segment_length: int = Field(default=5, ge=3)
    negative_z_threshold: float = Field(default=-1.5)
    positive_z_threshold: float = Field(default=1.5)
    min_event_steps: int = Field(default=2, ge=1)


class RecoveryConfig(BaseModel):
    """Post-disturbance event-centered recovery parameters."""

    model_config = ConfigDict(frozen=True)

    pre_event_window_steps: int = Field(default=6, ge=2)
    recovery_fraction_threshold: float = Field(default=0.9, gt=0.0, le=1.0)
    min_post_event_steps: int = Field(default=3, ge=2)
    require_deseasonalized: bool = True


class ResilienceConfig(BaseModel):
    """Configurable resilience dimension computation policy."""

    model_config = ConfigDict(frozen=True)

    compute_dimensions: bool = True
    allow_experimental_tri: bool = False


class AssessmentRequest(BaseModel):
    """Top-level configuration defining a reproducible Scientific Assessment."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    region_id: str | None = None
    region_name: str | None = None
    region_area_km2: float | None = Field(default=None, gt=0.0)
    analysis_start: datetime
    analysis_end: datetime
    target_cadence: TemporalCadence = TemporalCadence.MONTHLY
    aggregation_operator: AggregationOperator = AggregationOperator.MEAN
    qa_level: QaPolicyLevel = QaPolicyLevel.STANDARD
    smap_overpass_mode: OverpassMode = OverpassMode.AM_ONLY
    allow_imerg_early_late: bool = False
    allow_interpolation: bool = False
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)
    anomaly: AnomalyConfig = Field(default_factory=AnomalyConfig)
    trend: TrendConfig = Field(default_factory=TrendConfig)
    spatial: SpatialConfig = Field(default_factory=SpatialConfig)
    cross_variable: CrossVariableConfig = Field(default_factory=CrossVariableConfig)
    disturbance: DisturbanceConfig = Field(default_factory=DisturbanceConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    enabled_stages: tuple[str, ...] | None = None
    allow_partial_datasets: bool = True
    output_artifact_dir: str | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "AssessmentRequest":
        object.__setattr__(self, "analysis_start", ensure_utc(self.analysis_start))
        object.__setattr__(self, "analysis_end", ensure_utc(self.analysis_end))
        if self.analysis_end <= self.analysis_start:
            raise ValueError("analysis_end must be strictly after analysis_start")
        return self
