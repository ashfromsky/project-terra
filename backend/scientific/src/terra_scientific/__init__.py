"""PROJECT TERRA Scientific Core package."""

from terra_scientific._version import __version__
from terra_scientific.domain.enums import (
    AssessmentStatus,
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    TemporalCadence,
    TrendDirection,
)
from terra_scientific.domain.models.dataset import ScientificDataset, ScientificGridStack
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.domain.models.result import ScientificAssessmentResult
from terra_scientific.methods.registry import DEFAULT_METHOD_REGISTRY
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.readiness import ReadinessAssessmentReport, evaluate_assessment_readiness

__all__ = [
    "DEFAULT_METHOD_REGISTRY",
    "AssessmentRequest",
    "AssessmentStatus",
    "BaselineType",
    "DataSourceId",
    "QaPolicyLevel",
    "ReadinessAssessmentReport",
    "ScientificAssessmentResult",
    "ScientificAssessmentService",
    "ScientificDataset",
    "ScientificGridStack",
    "TemporalCadence",
    "TrendDirection",
    "__version__",
    "evaluate_assessment_readiness",
]
