"""Domain entities for persisted Core ingestion tracking records."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class IngestionOperationRecord:
    """User-owned tracking record linking an AOI and a GHS harmonization job."""

    id: UUID
    owner_id: UUID
    region_id: UUID | None
    ghs_job_id: str
    provider: str
    product: str
    status: str
    progress_pct: float
    dataset_id: str | None = None
    error_message: str | None = None
    error_category: str | None = None
    request_summary: dict[str, Any] = field(default_factory=dict)
    dataset_summary: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
