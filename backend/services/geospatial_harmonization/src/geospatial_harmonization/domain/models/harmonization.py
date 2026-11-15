"""Harmonization plan, resampling policy, transformation, and job domain models."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from geospatial_harmonization.domain.exceptions import (
    ErrorCategory,
    IncompatibleDatasetError,
    InvalidGridSpecError,
    InvalidTemporalSpecError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    SpatialDataset,
    VariableSemantics,
)
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.models.temporal import TemporalSpec, require_tz_aware

ResamplingMethod = Literal["nearest", "bilinear", "cubic", "average", "sum", "mode"]
OutputFormat = Literal["geotiff", "netcdf", "zarr", "parquet", "json"]
JobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]

_ALLOWED_RESAMPLING: dict[VariableSemantics, tuple[ResamplingMethod, ...]] = {
    "continuous_intensive": ("nearest", "bilinear", "cubic", "average"),
    "continuous_extensive": ("sum", "average", "nearest"),
    "categorical": ("nearest", "mode"),
    "qa_flag": ("nearest", "mode"),
    "coordinate": ("nearest",),
}


@dataclass(frozen=True, slots=True)
class ResamplingPolicy:
    """Semantics-driven resampling rules preventing QA and flux corruption."""

    intensive_method: ResamplingMethod = "bilinear"
    extensive_method: ResamplingMethod = "sum"
    categorical_method: ResamplingMethod = "nearest"
    qa_method: ResamplingMethod = "nearest"

    def _defaults(self) -> dict[VariableSemantics, ResamplingMethod]:
        return {
            "continuous_intensive": self.intensive_method,
            "continuous_extensive": self.extensive_method,
            "categorical": self.categorical_method,
            "qa_flag": self.qa_method,
            "coordinate": "nearest",
        }

    def __post_init__(self) -> None:
        for semantics in self._defaults():
            self.select_for(semantics)

    def select_for(
        self, semantics: VariableSemantics, override: ResamplingMethod | None = None
    ) -> ResamplingMethod:
        chosen = override if override is not None else self._defaults()[semantics]
        if chosen not in _ALLOWED_RESAMPLING[semantics]:
            raise QualityPolicyViolationError(f"Resampling '{chosen}' invalid for '{semantics}'")
        return chosen


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Structured quality verification outcome attached to harmonized outputs."""

    passed: bool
    valid_fraction: float
    nodata_fraction: float
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.valid_fraction <= 1.0 or not 0.0 <= self.nodata_fraction <= 1.0:
            raise QualityPolicyViolationError("Quality fractions must stay within [0, 1]")


@dataclass(frozen=True, slots=True)
class TargetGridTransformRequest:
    """Universal request contract for TargetGridTransformer independent of providers."""

    dataset: SpatialDataset
    target_grid: GridSpec
    variables: tuple[str, ...] | None = None
    resampling_policy: ResamplingPolicy = field(default_factory=ResamplingPolicy)
    resampling_overrides: dict[str, ResamplingMethod] = field(default_factory=dict)
    preserve_provenance: bool = True
    max_grid_pixels: int = 100_000_000

    def __post_init__(self) -> None:
        resolved = self.target_grid.resolved()
        if resolved.pixel_count > self.max_grid_pixels:
            raise InvalidGridSpecError("Target grid pixel count exceeds max_grid_pixels limit")
        if self.variables is not None and (
            not self.variables or any(v not in self.dataset.variables for v in self.variables)
        ):
            raise IncompatibleDatasetError("Requested variables must be a non-empty valid subset")
        for var_name, method in self.resampling_overrides.items():
            if var_name not in self.dataset.variables:
                raise IncompatibleDatasetError(f"Unknown override variable '{var_name}'")
            self.resampling_policy.select_for(self.dataset.variables[var_name].semantics, method)


@dataclass(frozen=True, slots=True)
class TargetGridTransformResult:
    """Standardized spatial transformation output with applied methods and QC report."""

    dataset: SpatialDataset
    target_grid: GridSpec
    methods_applied: dict[str, ResamplingMethod]
    quality_report: QualityReport
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.target_grid.width is None or self.target_grid.height is None:
            raise InvalidGridSpecError("TargetGridTransformResult requires a resolved GridSpec")


@dataclass(frozen=True, slots=True)
class HarmonizationPlan:
    """Declarative orchestration plan spanning retrieval, decoding, and harmonization."""

    plan_id: UUID
    provider: str
    product: str
    request_payload: dict[str, object]
    target_grid: GridSpec | None = None
    target_temporal: TemporalSpec | None = None
    resampling_policy: ResamplingPolicy = field(default_factory=ResamplingPolicy)
    variables: tuple[str, ...] = ()
    output_format: OutputFormat = "geotiff"

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.product.strip():
            raise IncompatibleDatasetError("HarmonizationPlan requires non-empty provider/product")
        if self.target_grid is not None:
            self.target_grid.resolved()

    def compute_idempotency_key(self) -> str:
        """Compute deterministic SHA-256 key over plan inputs (excluding random plan_id)."""
        payload = {
            "provider": self.provider.strip().lower(),
            "product": self.product.strip().lower(),
            "request_payload": dict(self.request_payload),
            "target_grid": asdict(self.target_grid) if self.target_grid is not None else None,
            "target_temporal": (
                asdict(self.target_temporal) if self.target_temporal is not None else None
            ),
            "variables": list(self.variables),
            "output_format": self.output_format,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HarmonizationJob:
    """Durable async execution record managed via PostgreSQL SKIP LOCKED leases."""

    job_id: UUID
    plan: HarmonizationPlan
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    attempt: int = 0
    max_attempts: int = 3
    locked_by: str | None = None
    lease_expires_at: datetime | None = None
    dataset_id: UUID | None = None
    error_message: str | None = None
    error_category: ErrorCategory | None = None
    next_retry_at: datetime | None = None
    progress_pct: int = 0
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        require_tz_aware(self.created_at, "created_at")
        require_tz_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise InvalidTemporalSpecError("updated_at cannot precede created_at")
        if self.lease_expires_at is not None:
            require_tz_aware(self.lease_expires_at, "lease_expires_at")
        if self.next_retry_at is not None:
            require_tz_aware(self.next_retry_at, "next_retry_at")
        if self.attempt < 0 or self.max_attempts < 1:
            raise IncompatibleDatasetError("attempt must be >= 0 and max_attempts >= 1")
        if not 0 <= self.progress_pct <= 100:
            raise IncompatibleDatasetError("progress_pct must lie within [0, 100]")


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """End-to-end harmonization result tying output dataset, assets, and QC together."""

    job_id: UUID
    dataset: SpatialDataset
    quality_report: QualityReport
    completed_at: datetime
    output_assets: tuple[AssetReference, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_tz_aware(self.completed_at, "completed_at")
