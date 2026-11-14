"""Unified storage usage monitoring and credential-safe policy reporting."""

from datetime import UTC, datetime

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.models.storage import StorageUsageSummary
from geospatial_harmonization.domain.ports import StorageLedgerRepository
from geospatial_harmonization.storage.quota import StorageQuotaManager
from geospatial_harmonization.storage.zones import StorageZoneManager


class StorageMonitoringService:
    """Produces unified zone usage, quota availability, savings, and policy summaries."""

    def __init__(
        self,
        ledger: StorageLedgerRepository,
        quota: StorageQuotaManager,
        zones: StorageZoneManager,
        settings: Settings | None = None,
    ) -> None:
        self._ledger = ledger
        self._quota = quota
        self._zones = zones
        self._settings = settings or get_settings()

    async def get_usage_summary(self, *, now: datetime | None = None) -> StorageUsageSummary:
        """Compute current budget utilization, per-zone consumption, savings, and warnings."""
        ref_now = (now or datetime.now(UTC)).astimezone(UTC)
        metrics = await self._ledger.get_usage_metrics(ref_now)
        budget = self._settings.ghs_storage_budget_bytes
        hard_limit_bytes = self._quota.hard_limit_bytes
        allocated = metrics.total_stored_bytes + metrics.reserved_bytes
        available = max(0, hard_limit_bytes - allocated)
        utilization = (allocated / budget) if budget > 0 else 0.0
        warnings = self._quota.evaluate_warnings(metrics)
        return StorageUsageSummary(
            budget_bytes=budget,
            warning_threshold=self._settings.ghs_storage_warning_threshold,
            hard_limit_threshold=self._settings.ghs_storage_hard_limit_threshold,
            hard_limit_bytes=hard_limit_bytes,
            total_stored_bytes=metrics.total_stored_bytes,
            object_count=metrics.object_count,
            reserved_bytes=metrics.reserved_bytes,
            available_budget_bytes=available,
            utilization_ratio=utilization,
            zones=metrics.zones,
            daily_growth_bytes=metrics.daily_growth_bytes,
            compression_savings_bytes=metrics.compression_savings_bytes,
            deduplication_savings_bytes=metrics.deduplication_savings_bytes,
            cleanup_deleted_objects=metrics.cleanup_deleted_objects,
            cleanup_reclaimed_bytes=metrics.cleanup_reclaimed_bytes,
            failed_uploads_count=metrics.failed_uploads_count,
            orphaned_objects_count=metrics.orphaned_objects_count,
            missing_referenced_objects_count=metrics.missing_referenced_objects_count,
            reconciliation_diff_bytes=metrics.last_reconciliation_diff_bytes,
            warnings=warnings,
            measured_at=ref_now,
        )

    def get_policy_summary(self) -> dict[str, object]:
        """Return active storage quota, zone, compression, and lifecycle settings safely."""
        cfg = self._settings
        return {
            "storage_backend": cfg.storage_backend,
            "quota": {
                "budget_bytes": cfg.ghs_storage_budget_bytes,
                "warning_threshold": cfg.ghs_storage_warning_threshold,
                "hard_limit_threshold": cfg.ghs_storage_hard_limit_threshold,
                "max_object_bytes": cfg.ghs_storage_max_object_bytes,
                "max_job_output_bytes": cfg.ghs_storage_max_job_output_bytes,
                "estimation_enabled": cfg.ghs_storage_estimation_enabled,
                "reservation_ttl_seconds": cfg.ghs_storage_reservation_ttl_seconds,
            },
            "zones": {
                zone: {
                    "retention_seconds": policy.retention_seconds,
                    "auto_cleanup_on_job_success": policy.auto_cleanup_on_job_success,
                    "immutable": policy.immutable,
                    "allow_deduplication": policy.allow_deduplication,
                }
                for zone, policy in (
                    ("raw", self._zones.policy_for("raw")),
                    ("intermediate", self._zones.policy_for("intermediate")),
                    ("derived", self._zones.policy_for("derived")),
                )
            },
            "compression": {
                "enabled": cfg.ghs_storage_compression_enabled,
                "raster_codec": cfg.ghs_storage_raster_codec,
                "raster_cog_enabled": cfg.ghs_storage_raster_cog_enabled,
                "raster_block_size": cfg.ghs_storage_raster_block_size,
                "netcdf_complevel": cfg.ghs_storage_netcdf_complevel,
                "zarr_codec": cfg.ghs_storage_zarr_codec,
                "zarr_target_chunk_bytes": cfg.ghs_storage_zarr_target_chunk_bytes,
                "allow_lossy_compression": cfg.ghs_storage_allow_lossy_compression,
                "min_recompress_savings_ratio": cfg.ghs_storage_min_recompress_savings_ratio,
            },
            "deduplication": {
                "enabled": cfg.ghs_storage_dedup_enabled,
                "verify_upload_integrity": cfg.ghs_storage_verify_upload_integrity,
            },
            "lifecycle": {
                "orphan_grace_seconds": cfg.ghs_storage_orphan_grace_seconds,
                "abandoned_temp_max_age_seconds": cfg.ghs_storage_abandoned_temp_max_age_seconds,
                "max_worker_concurrency": cfg.ghs_storage_max_worker_concurrency,
                "temp_max_bytes": cfg.ghs_storage_temp_max_bytes,
            },
        }
