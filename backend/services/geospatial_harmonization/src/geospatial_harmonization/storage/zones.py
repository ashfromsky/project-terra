"""Logical storage zone management for raw, intermediate, and derived data lake assets."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import StorageImmutabilityError
from geospatial_harmonization.domain.models.storage import StorageZone, ZoneRetentionPolicy

_PROVIDER_ZONE_SLUGS: dict[str, str] = {
    "modis": "modis",
    "gpm": "gpm",
    "gpm_imerg": "gpm",
    "smap": "smap",
    "nasa_power": "nasa-power",
    "nasa-power": "nasa-power",
}
_VALID_ZONES: frozenset[str] = frozenset({"raw", "intermediate", "derived"})


def _sanitize_segment(raw: str, *, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw.strip()).strip("-.")
    if not cleaned or cleaned in (".", ".."):
        return fallback
    return cleaned


def _validate_relative_key(key: str) -> str:
    if not key or "\x00" in key or "\\" in key or key.startswith("/"):
        raise ValueError(f"Invalid storage key: {key!r}")
    parts = key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe path segment in storage key: {key!r}")
    return str(PurePosixPath(*parts))


class StorageZoneManager:
    """Manages logical zone layout (raw, intermediate, derived), immutability, and retention."""

    def __init__(self, settings: Settings | None = None) -> None:
        cfg = settings or get_settings()
        raw_retention = (
            cfg.ghs_storage_raw_retention_days * 86400
            if cfg.ghs_storage_raw_retention_days is not None
            else None
        )
        derived_retention = (
            cfg.ghs_storage_derived_retention_days * 86400
            if cfg.ghs_storage_derived_retention_days is not None
            else None
        )
        self._policies: dict[StorageZone, ZoneRetentionPolicy] = {
            "raw": ZoneRetentionPolicy(
                zone="raw",
                retention_seconds=raw_retention,
                auto_cleanup_on_job_success=False,
                immutable=True,
                allow_deduplication=cfg.ghs_storage_dedup_enabled,
            ),
            "intermediate": ZoneRetentionPolicy(
                zone="intermediate",
                retention_seconds=cfg.ghs_storage_intermediate_retention_seconds,
                auto_cleanup_on_job_success=True,
                immutable=False,
                allow_deduplication=False,
            ),
            "derived": ZoneRetentionPolicy(
                zone="derived",
                retention_seconds=derived_retention,
                auto_cleanup_on_job_success=False,
                immutable=True,
                allow_deduplication=cfg.ghs_storage_dedup_enabled,
            ),
        }

    def provider_slug(self, provider: str) -> str:
        """Map canonical provider identifiers onto the Data Lake raw zone directory layout."""
        normalized = provider.strip().lower()
        if normalized in _PROVIDER_ZONE_SLUGS:
            return _PROVIDER_ZONE_SLUGS[normalized]
        return _sanitize_segment(normalized, fallback="other")

    def raw_key(
        self,
        provider: str,
        product: str,
        dataset_id: UUID | str,
        filename: str,
        *,
        content_sha256: str | None = None,
    ) -> str:
        """Build a canonical immutable key under ``raw/{provider}/...``."""
        prov_dir = self.provider_slug(provider)
        prod_dir = _sanitize_segment(product, fallback="product")
        bucket = (
            content_sha256[:16].lower()
            if content_sha256 and len(content_sha256) >= 16
            else _sanitize_segment(str(dataset_id), fallback="dataset")
        )
        safe_file = _sanitize_segment(PurePosixPath(filename).name, fallback="asset.bin")
        return _validate_relative_key(f"raw/{prov_dir}/{prod_dir}/{bucket}/{safe_file}")

    def intermediate_key(
        self,
        owner_id: UUID | str,
        filename: str,
        *,
        stage: str = "work",
    ) -> str:
        """Build a short-lived key under ``intermediate/`` for temporary processing artifacts."""
        owner = _sanitize_segment(str(owner_id), fallback="run")
        stage_dir = _sanitize_segment(stage, fallback="work")
        safe_file = _sanitize_segment(PurePosixPath(filename).name, fallback="artifact.bin")
        return _validate_relative_key(f"intermediate/{owner}/{stage_dir}/{safe_file}")

    def derived_key(
        self,
        dataset_id: UUID | str,
        filename: str,
        *,
        product: str | None = None,
        content_sha256: str | None = None,
    ) -> str:
        """Build a versioned or content-addressed key under ``derived/``."""
        scope = (
            _sanitize_segment(product, fallback="derived")
            if product
            else _sanitize_segment(str(dataset_id), fallback="dataset")
        )
        leaf_id = (
            content_sha256[:16].lower()
            if content_sha256 and len(content_sha256) >= 16
            else _sanitize_segment(str(dataset_id), fallback="dataset")
        )
        safe_file = _sanitize_segment(PurePosixPath(filename).name, fallback="output.tif")
        return _validate_relative_key(f"derived/{scope}/{leaf_id}/{safe_file}")

    def infer_zone(self, key: str) -> StorageZone:
        """Determine the logical storage zone from a validated storage key."""
        norm = _validate_relative_key(key)
        top = norm.split("/", 1)[0]
        if top not in _VALID_ZONES:
            raise ValueError(f"Key '{key}' does not belong to raw, intermediate, or derived zone")
        if top == "raw":
            return "raw"
        if top == "intermediate":
            return "intermediate"
        return "derived"

    def policy_for(self, zone: StorageZone) -> ZoneRetentionPolicy:
        """Return the retention and immutability policy configured for ``zone``."""
        return self._policies[zone]

    def expiration_for(self, zone: StorageZone, *, now: datetime | None = None) -> datetime | None:
        """Compute explicit expiration timestamp from zone retention policy, or None."""
        policy = self.policy_for(zone)
        if policy.retention_seconds is None:
            return None
        ref = (now or datetime.now(UTC)).astimezone(UTC)
        return ref + timedelta(seconds=policy.retention_seconds)

    def assert_writable(self, key: str, *, exists_in_store: bool) -> StorageZone:
        """Enforce immutability rules before writing an object to a zone."""
        zone = self.infer_zone(key)
        policy = self.policy_for(zone)
        if policy.immutable and exists_in_store:
            raise StorageImmutabilityError(f"Cannot overwrite immutable {zone} asset at '{key}'")
        return zone

    def assert_deletable(self, key: str, *, reason: str) -> StorageZone:
        """Prevent unsafe automatic deletion of source data upon job completion or sweeps."""
        zone = self.infer_zone(key)
        policy = self.policy_for(zone)
        if zone == "raw" and reason in (
            "job_completed",
            "job_failed",
            "auto_intermediate_cleanup",
            "expired_ttl",
            "orphan_sweep",
        ):
            raise StorageImmutabilityError(
                f"Source asset '{key}' in raw zone cannot be automatically deleted on '{reason}'"
            )
        if not policy.auto_cleanup_on_job_success and reason == "job_completed":
            raise StorageImmutabilityError(
                f"Asset '{key}' in {zone} zone is protected from post-job automatic cleanup"
            )
        return zone
