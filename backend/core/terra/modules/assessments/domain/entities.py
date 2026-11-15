"""Domain entity for persisted scientific assessments."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

AssessmentLifecycleStatus = Literal[
    "queued",
    "running",
    "completed",
    "completed_partial",
    "insufficient_data",
    "failed",
]


@dataclass(frozen=True)
class ScientificAssessment:
    """User-owned persisted scientific assessment request, status, and deterministic output."""

    id: UUID
    owner_id: UUID
    region_id: UUID | None
    title: str
    status: AssessmentLifecycleStatus
    request_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    ghs_dataset_ids: list[str] = field(default_factory=list)
    inline_datasets: list[dict[str, Any]] = field(default_factory=list)
    result_payload: dict[str, Any] | None = None
    artifact_paths: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    completed_at: datetime | None = None
