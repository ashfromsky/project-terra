"""Domain contracts for adaptive source- and method-aware readiness diagnostics."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import DataSourceId, PriorityTier, TemporalCadence

READINESS_SPEC_VERSION = "1.0.0"

CriterionStatus = Literal["passed", "warning", "failed"]
MetricAvailabilityStatus = Literal["available", "degraded", "unavailable", "deferred"]
ReadinessLevel = Literal["ready", "partial", "insufficient"]


class DatasetReadinessProfile(BaseModel):
    """Observed dataset coverage, cadence, QA presence, and adaptive thresholds."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    source_id: DataSourceId
    product: str
    variables: list[str] = Field(default_factory=list)
    native_cadence: TemporalCadence
    target_cadence: TemporalCadence
    observation_start: datetime | None = None
    observation_end: datetime | None = None
    span_years: float = Field(default=0.0, ge=0.0)
    raw_step_count: int = Field(default=0, ge=0)
    valid_qa_count: int = Field(default=0, ge=0)
    valid_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    qa_layers_present: list[str] = Field(default_factory=list)
    has_grid_stack: bool = False
    min_qa_fraction_required: float = Field(ge=0.0, le=1.0)
    min_step_coverage_required: float = Field(ge=0.0, le=1.0)
    min_trend_samples_required: int = Field(ge=4)
    min_baseline_years_required: int = Field(ge=1)
    status: ReadinessLevel
    notes: list[str] = Field(default_factory=list)


class ReadinessCriterion(BaseModel):
    """Single source- or method-specific requirement evaluated against actual inputs."""

    model_config = ConfigDict(frozen=True)

    criterion_id: str
    category: str
    dataset_id: str | None = None
    variable_name: str | None = None
    stage_or_metric: str
    title: str
    required_summary: str
    actual_summary: str
    required_value: float | int | str | None = None
    actual_value: float | int | str | None = None
    unit: str | None = None
    status: CriterionStatus
    scientific_rationale: str
    missing_gap: str | None = None
    remediation: str | None = None
    spec_version: str = READINESS_SPEC_VERSION


class MetricAvailability(BaseModel):
    """Availability status for one scientific pipeline stage or derived metric."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    label: str
    priority: PriorityTier
    required: bool = True
    status: MetricAvailabilityStatus
    blocking_criteria: list[str] = Field(default_factory=list)
    reason: str
    remediation: str | None = None


class ReadinessAssessmentReport(BaseModel):
    """Complete pre- or post-execution adaptive readiness evaluation."""

    model_config = ConfigDict(frozen=True)

    spec_version: str = READINESS_SPEC_VERSION
    evaluated_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    overall_status: ReadinessLevel
    summary: str
    datasets: list[DatasetReadinessProfile] = Field(default_factory=list)
    criteria: list[ReadinessCriterion] = Field(default_factory=list)
    metrics: list[MetricAvailability] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    suggested_window_start: datetime | None = None
    suggested_window_end: datetime | None = None
