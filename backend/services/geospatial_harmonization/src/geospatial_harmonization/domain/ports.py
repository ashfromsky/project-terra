"""Domain ports (Protocols) separating GHS boundaries from infrastructure."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    SpatialDataset,
)
from geospatial_harmonization.domain.models.harmonization import (
    HarmonizationJob,
    TargetGridTransformRequest,
    TargetGridTransformResult,
)


class DataHandler(Protocol):
    """Provider-specific handler interface returning canonical SpatialDataset envelopes."""

    @property
    def provider(self) -> str: ...
    @property
    def supported_products(self) -> tuple[str, ...]: ...
    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset: ...


class AssetReader(Protocol):
    """Format-specific lazy decoder emitting DecodedDataset without provider logic."""

    @property
    def data_format(self) -> DataFormat: ...
    def supports(self, asset: AssetReference, header: bytes = b"") -> bool: ...
    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset: ...


class GridTransformer(Protocol):
    """Source-agnostic spatial grid transformation engine contract."""

    def transform(self, request: TargetGridTransformRequest) -> TargetGridTransformResult: ...


class StoragePort(Protocol):
    """Object/asset storage abstraction for raw, intermediate, and derived datasets."""

    async def put_bytes(
        self, key: str, data: bytes, media_type: str = "application/octet-stream"
    ) -> AssetReference: ...
    async def put_file(
        self, key: str, path: Path, media_type: str = "application/octet-stream"
    ) -> AssetReference: ...
    async def get_bytes(self, key: str) -> bytes: ...
    async def materialize_to_path(self, key: str, dest: Path) -> Path: ...
    async def exists(self, key: str) -> bool: ...


class JobRepository(Protocol):
    """Persistence contract for durable harmonization jobs and worker lease transitions."""

    async def create(self, job: HarmonizationJob) -> None: ...
    async def get_by_id(self, job_id: UUID) -> HarmonizationJob | None: ...
    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int, now: datetime
    ) -> HarmonizationJob | None: ...
    async def mark_succeeded(
        self, job_id: UUID, dataset_id: UUID, completed_at: datetime
    ) -> None: ...
    async def mark_failed(self, job_id: UUID, error_message: str, failed_at: datetime) -> None: ...


class DatasetRepository(Protocol):
    """Persistence contract for harmonized canonical dataset metadata."""

    async def save(self, dataset: SpatialDataset) -> None: ...
    async def get_by_id(self, dataset_id: UUID) -> SpatialDataset | None: ...
    async def list_recent(
        self, limit: int = 50, provider: str | None = None
    ) -> tuple[SpatialDataset, ...]: ...
