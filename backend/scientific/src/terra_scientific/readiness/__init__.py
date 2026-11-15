"""Adaptive scientific data readiness specifications and diagnostics."""

from terra_scientific.readiness.evaluator import evaluate_assessment_readiness
from terra_scientific.readiness.models import (
    READINESS_SPEC_VERSION,
    CriterionStatus,
    DatasetReadinessProfile,
    MetricAvailability,
    MetricAvailabilityStatus,
    ReadinessAssessmentReport,
    ReadinessCriterion,
    ReadinessLevel,
)
from terra_scientific.readiness.specs import (
    SourceReadinessProfile,
    get_source_readiness_profile,
    resolve_aggregation_min_coverage,
    resolve_baseline_requirements,
    resolve_qa_sufficiency_threshold,
    resolve_trend_requirements,
)

__all__ = [
    "READINESS_SPEC_VERSION",
    "CriterionStatus",
    "DatasetReadinessProfile",
    "MetricAvailability",
    "MetricAvailabilityStatus",
    "ReadinessAssessmentReport",
    "ReadinessCriterion",
    "ReadinessLevel",
    "SourceReadinessProfile",
    "evaluate_assessment_readiness",
    "get_source_readiness_profile",
    "resolve_aggregation_min_coverage",
    "resolve_baseline_requirements",
    "resolve_qa_sufficiency_threshold",
    "resolve_trend_requirements",
]
