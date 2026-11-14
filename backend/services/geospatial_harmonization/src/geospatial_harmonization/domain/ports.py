"""Domain ports (Protocols) separating GHS boundaries from infrastructure."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
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
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    ObjectStatus,
    ReferenceKind,
    StorageObjectRecord,
    StorageReservation,
    StorageUsageMetricsSnapshot,
    StorageZone,
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


class StorageLedgerRepository(Protocol):
    """Transactional ledger contract for quotas, reservations, dedup objects, and refs."""

    async def ensure_ledger_initialized(self, now: datetime) -> None: ...
    async def reserve_capacity(
        self,
        reservation: StorageReservation,
        *,
        budget_bytes: int,
        hard_limit_threshold: float,
        max_object_bytes: int,
        max_job_output_bytes: int,
        now: datetime,
    ) -> StorageReservation: ...
    async def commit_reservation(
        self, reservation_id: UUID, actual_bytes: int, now: datetime
    ) -> StorageReservation: ...
    async def release_reservation(
        self,
        reservation_id: UUID,
        status: Literal["released", "failed"],
        now: datetime,
        reason: str | None = None,
    ) -> StorageReservation: ...
    async def reconcile_expired_reservations(
        self, now: datetime
    ) -> tuple[StorageReservation, ...]: ...
    async def get_reservation(self, reservation_id: UUID) -> StorageReservation | None: ...
    async def list_active_reservations(self, now: datetime) -> tuple[StorageReservation, ...]: ...
    async def get_object(self, object_key: str) -> StorageObjectRecord | None: ...
    async def find_active_by_checksum(
        self, checksum_sha256: str, zone: StorageZone | None = None
    ) -> StorageObjectRecord | None: ...
    async def register_object_and_ref(
        self,
        obj: StorageObjectRecord,
        ref: AssetReferenceLink,
        now: datetime,
        *,
        dedup_saved_bytes: int = 0,
    ) -> tuple[StorageObjectRecord, bool]: ...
    async def add_asset_reference(self, ref: AssetReferenceLink, now: datetime) -> bool: ...
    async def remove_asset_references_for_owner(
        self, ref_kind: ReferenceKind, ref_owner_id: str, now: datetime
    ) -> tuple[str, ...]: ...
    async def has_active_references(self, object_key: str) -> bool: ...
    async def mark_object_orphan(
        self, object_key: str, marked_at: datetime
    ) -> StorageObjectRecord | None: ...
    async def delete_object_record(self, object_key: str, deleted_at: datetime) -> bool: ...
    async def list_objects(
        self, zone: StorageZone | None = None, status: ObjectStatus | None = None
    ) -> tuple[StorageObjectRecord, ...]: ...
    async def list_expired_intermediate_objects(
        self, now: datetime
    ) -> tuple[StorageObjectRecord, ...]: ...
    async def list_orphan_sweep_candidates(
        self, marked_before: datetime
    ) -> tuple[StorageObjectRecord, ...]: ...
    async def record_audit_event(
        self,
        event_type: str,
        zone: StorageZone | None,
        object_key: str | None,
        bytes_delta: int,
        saved_bytes: int,
        details: dict[str, object],
        now: datetime,
    ) -> None: ...
    async def get_usage_metrics(self, now: datetime) -> StorageUsageMetricsSnapshot: ...


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
