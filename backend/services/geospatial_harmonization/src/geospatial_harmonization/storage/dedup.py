"""Content-addressed deduplication and integrity verification across storage zones."""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import StorageIntegrityError
from geospatial_harmonization.domain.models.dataset import AssetReference, DataFormat
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    StorageObjectRecord,
    StorageZone,
)
from geospatial_harmonization.domain.ports import StorageLedgerRepository, StoragePort
from geospatial_harmonization.storage.zones import StorageZoneManager


@dataclass(frozen=True, slots=True)
class DeduplicatedAssetResult:
    """Outcome of storing or deduplicating an asset in the data lake ledger."""

    record: StorageObjectRecord
    asset_reference: AssetReference
    deduplicated: bool
    saved_bytes: int


def compute_file_sha256(path: Path, chunk_size: int = 1_048_576) -> tuple[str, int]:
    """Stream a file in bounded chunks and return (sha256_hex, size_bytes)."""
    if not path.is_file():
        raise FileNotFoundError(f"Cannot compute checksum; file not found: {path}")
    hasher = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
            total += len(chunk)
    return hasher.hexdigest(), total


class ContentDeduplicationService:
    """Eliminates redundant binary uploads while keeping per-job provenance distinct."""

    def __init__(
        self,
        storage: StoragePort,
        ledger: StorageLedgerRepository,
        zones: StorageZoneManager,
        settings: Settings | None = None,
    ) -> None:
        self._storage = storage
        self._ledger = ledger
        self._zones = zones
        self._settings = settings or get_settings()

    def _build_uri(self, object_key: str) -> str:
        root_dir = getattr(self._storage, "root_dir", None)
        if isinstance(root_dir, Path):
            return (root_dir / object_key).resolve().as_uri()
        bucket = getattr(self._storage, "_bucket", None)
        prefix = getattr(self._storage, "_prefix", "")
        if isinstance(bucket, str) and bucket:
            full = f"{prefix}/{object_key}" if prefix else object_key
            return f"s3://{bucket}/{full}"
        parsed = urlparse(object_key)
        return object_key if parsed.scheme else f"ghs://{object_key}"

    async def store_or_deduplicate_file(
        self,
        *,
        source_path: Path,
        zone: StorageZone,
        object_key: str,
        ref: AssetReferenceLink,
        media_type: str,
        data_format: DataFormat,
        original_size_bytes: int | None = None,
        compression_codec: str | None = None,
        verify_sha256: str | None = None,
        now: datetime | None = None,
    ) -> DeduplicatedAssetResult:
        """Upload source_path if unique, or share an existing verified identical object."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        inferred_zone = self._zones.infer_zone(object_key)
        if inferred_zone != zone:
            raise StorageIntegrityError(
                f"Object key '{object_key}' belongs to zone '{inferred_zone}', not '{zone}'"
            )

        chunk_size = self._settings.ghs_storage_stream_chunk_bytes
        digest, size_bytes = compute_file_sha256(source_path, chunk_size=chunk_size)
        if verify_sha256 is not None and digest.lower() != verify_sha256.lower():
            raise StorageIntegrityError(
                f"Checksum verification failed for '{source_path}': "
                f"expected {verify_sha256}, got {digest}"
            )

        zone_policy = self._zones.policy_for(zone)
        if self._settings.ghs_storage_dedup_enabled and zone_policy.allow_deduplication:
            candidate = await self._ledger.find_active_by_checksum(digest, zone=zone)
            if candidate is not None and candidate.size_bytes == size_bytes:
                physical = await self._storage.head_object(candidate.object_key)
                if physical is not None and physical.size_bytes == size_bytes:
                    shared_ref = AssetReferenceLink(
                        object_key=candidate.object_key,
                        ref_kind=ref.ref_kind,
                        ref_owner_id=ref.ref_owner_id,
                        asset_id=ref.asset_id,
                        provider=ref.provider,
                        product=ref.product,
                        created_at=ref_now,
                        metadata=dict(ref.metadata),
                    )
                    updated, _ = await self._ledger.register_object_and_ref(
                        candidate,
                        shared_ref,
                        ref_now,
                        dedup_saved_bytes=size_bytes,
                    )
                    return DeduplicatedAssetResult(
                        record=updated,
                        asset_reference=AssetReference(
                            asset_id=candidate.object_key,
                            uri=self._build_uri(candidate.object_key),
                            data_format=candidate.data_format,
                            media_type=candidate.media_type,
                            checksum_sha256=digest,
                            size_bytes=size_bytes,
                        ),
                        deduplicated=True,
                        saved_bytes=size_bytes,
                    )

        exists_remote = await self._storage.exists(object_key)
        self._zones.assert_writable(object_key, exists_in_store=exists_remote)
        info = await self._storage.put_file_stream(
            object_key,
            source_path,
            media_type=media_type,
            chunk_size=chunk_size,
            verify_sha256=digest,
        )
        if self._settings.ghs_storage_verify_upload_integrity:
            head = await self._storage.head_object(object_key)
            if head is None or head.size_bytes != size_bytes:
                raise StorageIntegrityError(
                    f"Post-upload integrity check failed for '{object_key}'"
                )

        record = StorageObjectRecord(
            object_key=object_key,
            zone=zone,
            content_sha256=digest,
            size_bytes=info.size_bytes,
            original_size_bytes=original_size_bytes,
            media_type=media_type,
            data_format=data_format,
            compression_codec=compression_codec,
            ref_count=0,
            status="active",
            expires_at=self._zones.expiration_for(zone, now=ref_now),
            created_at=ref_now,
            updated_at=ref_now,
        )
        linked_ref = (
            ref
            if ref.object_key == object_key
            else AssetReferenceLink(
                object_key=object_key,
                ref_kind=ref.ref_kind,
                ref_owner_id=ref.ref_owner_id,
                asset_id=ref.asset_id,
                provider=ref.provider,
                product=ref.product,
                created_at=ref_now,
                metadata=dict(ref.metadata),
            )
        )
        persisted, _ = await self._ledger.register_object_and_ref(record, linked_ref, ref_now)
        return DeduplicatedAssetResult(
            record=persisted,
            asset_reference=AssetReference(
                asset_id=object_key,
                uri=self._build_uri(object_key),
                data_format=data_format,
                media_type=media_type,
                checksum_sha256=digest,
                size_bytes=info.size_bytes,
            ),
            deduplicated=False,
            saved_bytes=0,
        )

    async def store_or_deduplicate_bytes(
        self,
        *,
        payload: bytes,
        zone: StorageZone,
        object_key: str,
        ref: AssetReferenceLink,
        media_type: str,
        data_format: DataFormat,
        now: datetime | None = None,
    ) -> DeduplicatedAssetResult:
        """Stage payload bytes cleanly into a bounded temp file and store/deduplicate it."""
        temp_parent = self._settings.ghs_storage_temp_dir
        if temp_parent is not None:
            temp_parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(temp_parent) if temp_parent is not None else None,
            prefix=".ghs-tmp-dedup-",
        )
        tmp = Path(tmp_path)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            return await self.store_or_deduplicate_file(
                source_path=tmp,
                zone=zone,
                object_key=object_key,
                ref=ref,
                media_type=media_type,
                data_format=data_format,
                now=now,
            )
        finally:
            tmp.unlink(missing_ok=True)
