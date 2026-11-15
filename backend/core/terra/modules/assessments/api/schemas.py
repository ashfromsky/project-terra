"""API request and response schemas for Scientific Assessments."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field
from terra_scientific.domain.models.readiness import ReadinessAssessmentReport
from terra_scientific.methods.registry import MethodSpec

from terra.api.schemas import CamelModel
from terra.modules.assessments.domain.entities import (
    AssessmentLifecycleStatus,
    ScientificAssessment,
)


class MethodCatalogItemResponse(CamelModel):
    """Catalog metadata describing an implemented (P0/P1) or deferred (P2) scientific method."""

    method_id: str
    version: str
    name: str
    priority: str
    implemented: bool
    formula_summary: str
    assumptions: list[str]
    limitations: list[str]
    reference: str

    @classmethod
    def from_spec(cls, spec: MethodSpec) -> "MethodCatalogItemResponse":
        """Build API response from Scientific Core MethodSpec."""
        return cls(
            method_id=spec.method_id,
            version=spec.version,
            name=spec.name,
            priority=spec.priority.value,
            implemented=spec.implemented,
            formula_summary=spec.formula_summary,
            assumptions=list(spec.assumptions),
            limitations=list(spec.limitations),
            reference=spec.reference,
        )


class CreateAssessmentRequest(CamelModel):
    """Request payload creating and optionally executing a Scientific Assessment."""

    title: str = Field(min_length=1, max_length=255)
    region_id: UUID | None = None
    execute_now: bool = True
    request_config: dict[str, Any]
    ghs_dataset_ids: list[str] = Field(default_factory=list)
    inline_datasets: list[dict[str, Any]] = Field(default_factory=list)


class AssessmentSummaryResponse(CamelModel):
    """Summary representation of a persisted Scientific Assessment."""

    id: UUID
    owner_id: UUID
    region_id: UUID | None
    title: str
    status: AssessmentLifecycleStatus
    ghs_dataset_ids: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @classmethod
    def from_domain(cls, assessment: ScientificAssessment) -> "AssessmentSummaryResponse":
        """Map domain ScientificAssessment into summary response."""
        return cls(
            id=assessment.id,
            owner_id=assessment.owner_id,
            region_id=assessment.region_id,
            title=assessment.title,
            status=assessment.status,
            ghs_dataset_ids=list(assessment.ghs_dataset_ids),
            error_message=assessment.error_message,
            created_at=assessment.created_at,
            updated_at=assessment.updated_at,
            completed_at=assessment.completed_at,
        )


class AssessmentDetailResponse(AssessmentSummaryResponse):
    """Detailed representation including full Scientific Core output payload and artifacts."""

    request_config: dict[str, Any]
    result: dict[str, Any] | None
    artifact_paths: dict[str, str]

    @classmethod
    def from_domain_detail(cls, assessment: ScientificAssessment) -> "AssessmentDetailResponse":
        """Map domain ScientificAssessment into detailed response."""
        return cls(
            id=assessment.id,
            owner_id=assessment.owner_id,
            region_id=assessment.region_id,
            title=assessment.title,
            status=assessment.status,
            ghs_dataset_ids=list(assessment.ghs_dataset_ids),
            error_message=assessment.error_message,
            created_at=assessment.created_at,
            updated_at=assessment.updated_at,
            completed_at=assessment.completed_at,
            request_config=dict(assessment.request_config),
            result=dict(assessment.result_payload)
            if assessment.result_payload is not None
            else None,
            artifact_paths=dict(assessment.artifact_paths),
        )


class CompareAssessmentsRequest(CamelModel):
    """Request payload selecting two completed user assessments for comparison."""

    primary_assessment_id: UUID
    comparison_assessment_id: UUID


class VariableComparisonSummary(CamelModel):
    """Variable-level trend, resilience, and series mean deltas between two runs."""

    variable_name: str
    primary_sens_slope: float | None = None
    comparison_sens_slope: float | None = None
    sens_slope_delta: float | None = None
    slope_unit: str | None = None
    primary_direction: str | None = None
    comparison_direction: str | None = None
    primary_p_value: float | None = None
    comparison_p_value: float | None = None
    primary_resistance: float | None = None
    comparison_resistance: float | None = None
    resistance_delta: float | None = None
    primary_recovery: float | None = None
    comparison_recovery: float | None = None
    recovery_delta: float | None = None
    primary_stability: float | None = None
    comparison_stability: float | None = None
    stability_delta: float | None = None
    primary_sensitivity: float | None = None
    comparison_sensitivity: float | None = None
    sensitivity_delta: float | None = None
    primary_mean_value: float | None = None
    comparison_mean_value: float | None = None
    mean_value_delta: float | None = None


class AssessmentComparisonResponse(CamelModel):
    """Side-by-side scientific comparison payload between two assessments."""

    primary: AssessmentDetailResponse
    comparison: AssessmentDetailResponse
    shared_variables: list[str]
    primary_only_variables: list[str]
    comparison_only_variables: list[str]
    variable_comparisons: list[VariableComparisonSummary]
    compatibility_warnings: list[str]
    methodology_notes: list[str]


class AssessmentArtifactItemResponse(CamelModel):
    """Descriptor and download endpoints for a persisted assessment artifact."""

    name: str
    object_key: str
    content_type: str
    size_bytes: int
    checksum_sha256: str | None = None
    storage_backend: str
    download_path: str
    presigned_url: str | None = None
    presigned: bool = False


class AssessmentReadinessRequest(CamelModel):
    """Request payload evaluating pre-run scientific readiness for datasets and AOI."""

    region_id: UUID | None = None
    request_config: dict[str, Any]
    ghs_dataset_ids: list[str] = Field(default_factory=list)
    inline_datasets: list[dict[str, Any]] = Field(default_factory=list)


class DatasetReadinessProfileResponse(CamelModel):
    """Per-dataset observed coverage, QA presence, and adaptive thresholds."""

    dataset_id: str
    source_id: str
    product: str
    variables: list[str] = Field(default_factory=list)
    native_cadence: str
    target_cadence: str
    observation_start: datetime | None = None
    observation_end: datetime | None = None
    span_years: float = 0.0
    raw_step_count: int = 0
    valid_qa_count: int = 0
    valid_fraction: float = 0.0
    qa_layers_present: list[str] = Field(default_factory=list)
    has_grid_stack: bool = False
    min_qa_fraction_required: float
    min_step_coverage_required: float
    min_trend_samples_required: int
    min_baseline_years_required: int
    status: str
    notes: list[str] = Field(default_factory=list)


class ReadinessCriterionResponse(CamelModel):
    """Evaluated dataset/method readiness criterion with required vs actual diagnostics."""

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
    status: str
    scientific_rationale: str
    missing_gap: str | None = None
    remediation: str | None = None
    spec_version: str


class MetricAvailabilityResponse(CamelModel):
    """Availability status of one scientific stage or derived metric."""

    metric_id: str
    label: str
    priority: str
    required: bool = True
    status: str
    blocking_criteria: list[str] = Field(default_factory=list)
    reason: str
    remediation: str | None = None


class AssessmentReadinessResponse(CamelModel):
    """Structured pre-run or post-run adaptive readiness diagnostic report."""

    spec_version: str
    evaluated_at_utc: datetime
    overall_status: str
    summary: str
    datasets: list[DatasetReadinessProfileResponse] = Field(default_factory=list)
    criteria: list[ReadinessCriterionResponse] = Field(default_factory=list)
    metrics: list[MetricAvailabilityResponse] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    suggested_window_start: datetime | None = None
    suggested_window_end: datetime | None = None

    @classmethod
    def from_scientific(cls, report: ReadinessAssessmentReport) -> "AssessmentReadinessResponse":
        """Convert pure Scientific Core ReadinessAssessmentReport to Core CamelModel."""
        return cls.model_validate(report.model_dump(mode="python"))
