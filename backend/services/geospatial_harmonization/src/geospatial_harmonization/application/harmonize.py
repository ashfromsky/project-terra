"""Application orchestration pipeline connecting handlers, transformers, QC, and ports."""

import asyncio
import logging
import shutil
import tempfile
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

import numpy as np

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.exceptions import ObjectTooLargeError
from geospatial_harmonization.domain.models.dataset import AssetReference, SpatialDataset
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.models.harmonization import (
    HarmonizationPlan,
    ProcessingResult,
    QualityReport,
    TargetGridTransformRequest,
)
from geospatial_harmonization.domain.models.storage import (
    AssetReferenceLink,
    CompressionCodec,
    ReferenceKind,
    StorageReservation,
    StorageZone,
)
from geospatial_harmonization.domain.ports import (
    DatasetRepository,
    StorageLedgerRepository,
    StoragePort,
)
from geospatial_harmonization.handlers.registry import HandlerRegistry
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.storage.compression import DataCompressionManager
from geospatial_harmonization.storage.dedup import ContentDeduplicationService, compute_file_sha256
from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
from geospatial_harmonization.storage.quota import ReservationHandle, StorageQuotaManager
from geospatial_harmonization.storage.zones import StorageZoneManager
from geospatial_harmonization.transformations.quality import QualityPolicy, QualityValidator
from geospatial_harmonization.transformations.transformer import TargetGridTransformer

logger = logging.getLogger(__name__)

_HANDLER_TMP_PREFIXES = ("ghs_modis_", "ghs_imerg_", "ghs_smap_", "ghs_power_", "ghs_generic_")


def _local_asset_path(asset: AssetReference) -> Path | None:
    parsed = urlparse(asset.uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme:
        return Path(asset.uri)
    return None


def _estimate_uncompressed_raster_bytes(dataset: SpatialDataset, asset_path: Path) -> int | None:
    if dataset.spatial_metadata.grid is None:
        return None
    var_spec = dataset.variables.get(asset_path.stem)
    if var_spec is None:
        return None
    try:
        itemsize = int(np.dtype(var_spec.dtype).itemsize)
    except Exception:
        return None
    resolved = dataset.spatial_metadata.grid.resolved()
    if resolved.width is None or resolved.height is None:
        return None
    return max(0, resolved.width * resolved.height * itemsize)


class HarmonizationService:
    """End-to-end use case coordinating retrieval, spatial resampling, QC, and persistence."""

    def __init__(
        self,
        *,
        handlers: HandlerRegistry,
        storage: StoragePort,
        datasets: DatasetRepository,
        readers: ReaderRegistry | None = None,
        quality_policy: QualityPolicy | None = None,
        max_grid_pixels: int = 100_000_000,
        settings: Settings | None = None,
        ledger: StorageLedgerRepository | None = None,
        zones: StorageZoneManager | None = None,
        quota: StorageQuotaManager | None = None,
        dedup: ContentDeduplicationService | None = None,
        lifecycle: StorageLifecycleManager | None = None,
        compression: DataCompressionManager | None = None,
    ) -> None:
        self._handlers = handlers
        self._storage = storage
        self._datasets = datasets
        self._readers = readers or build_default_reader_registry()
        self._quality_policy = quality_policy or QualityPolicy()
        self._max_grid_pixels = max_grid_pixels
        self._settings = settings
        self._ledger = ledger
        self._zones = zones or (StorageZoneManager(settings) if settings is not None else None)
        self._quota = quota
        self._dedup = dedup
        self._lifecycle = lifecycle
        self._compression = compression or DataCompressionManager(settings=settings)

    def _asset_storage_uri(self, object_key: str) -> str:
        if self._settings is not None:
            if self._settings.storage_backend == "s3" and self._settings.s3_bucket:
                return f"s3://{self._settings.s3_bucket}/{object_key}"
            return (self._settings.local_storage_dir / object_key).resolve().as_uri()
        return object_key

    def _ensure_temp_capacity(self, estimated_bytes: int) -> Path | None:
        if self._settings is None:
            return None
        temp_base = self._settings.ghs_storage_temp_dir
        cap = self._settings.ghs_storage_temp_max_bytes
        if temp_base is not None:
            temp_base.mkdir(parents=True, exist_ok=True)
            used_bytes = sum(f.stat().st_size for f in temp_base.rglob("*") if f.is_file())
            if used_bytes + min(estimated_bytes, cap) > cap and used_bytes > 0:
                raise ObjectTooLargeError(
                    f"Temporary directory '{temp_base}' usage ({used_bytes} B) plus estimated "
                    f"scratch ({estimated_bytes} B) exceeds cap {cap} B",
                    requested_bytes=used_bytes + estimated_bytes,
                    limit_bytes=cap,
                    scope="temp_storage",
                )
        if self._settings.ghs_storage_estimation_enabled and estimated_bytes > cap:
            raise ObjectTooLargeError(
                f"Estimated working scratch size {estimated_bytes} B exceeds temp cap {cap} B",
                requested_bytes=estimated_bytes,
                limit_bytes=cap,
                scope="temp_storage",
            )
        check_dir = temp_base or Path(tempfile.gettempdir())
        free_bytes = shutil.disk_usage(str(check_dir)).free
        if estimated_bytes > free_bytes:
            raise ObjectTooLargeError(
                f"Insufficient temporary disk free space ({free_bytes} B < {estimated_bytes} B)",
                requested_bytes=estimated_bytes,
                limit_bytes=free_bytes,
                scope="temp_disk_free",
            )
        return temp_base

    def _check_object_size_limit(self, size_bytes: int) -> None:
        if self._settings is not None and size_bytes > self._settings.ghs_storage_max_object_bytes:
            raise ObjectTooLargeError(
                f"Object size {size_bytes} B exceeds max object limit "
                f"{self._settings.ghs_storage_max_object_bytes} B",
                requested_bytes=size_bytes,
                limit_bytes=self._settings.ghs_storage_max_object_bytes,
                scope="object",
            )

    def _cleanup_handler_temp_dirs(
        self, dataset: SpatialDataset | None, temp_base: Path | None
    ) -> None:
        if dataset is None:
            return
        allowed_roots = {Path(tempfile.gettempdir()).resolve()}
        if temp_base is not None:
            allowed_roots.add(temp_base.resolve())
        seen_dirs: set[Path] = set()
        for asset in dataset.assets:
            local_path = _local_asset_path(asset)
            if local_path is None:
                continue
            parent = local_path.resolve().parent
            if (
                parent not in seen_dirs
                and parent.parent in allowed_roots
                and parent.name.startswith(_HANDLER_TMP_PREFIXES)
            ):
                seen_dirs.add(parent)
                shutil.rmtree(parent, ignore_errors=True)

    async def _ensure_reservation_headroom(
        self,
        *,
        needed_bytes: int,
        already_reserved_bytes: int,
        actual_new_bytes: int,
        zone: StorageZone,
        job_id: str,
        extra_reservations: list[StorageReservation],
        now: datetime,
    ) -> int:
        total_reserved = already_reserved_bytes + sum(r.reserved_bytes for r in extra_reservations)
        projected = actual_new_bytes + needed_bytes
        if projected <= total_reserved or self._quota is None:
            return 0
        shortfall = projected - total_reserved
        extra = await self._quota.reserve_for_operation(
            estimated_bytes=shortfall,
            zone=zone,
            operation=f"{zone}_overflow_reserve",
            job_id=job_id,
            now=now,
        )
        extra_reservations.append(extra)
        return extra.reserved_bytes

    async def _persist_zone_file(
        self,
        *,
        zone: StorageZone,
        object_key: str,
        src_path: Path,
        asset: AssetReference,
        ref_kind: ReferenceKind,
        ref_owner_id: str,
        dataset: SpatialDataset,
        now: datetime,
        original_size_bytes: int | None,
        compression_codec: CompressionCodec,
        job_id: str,
        reservation_handle: ReservationHandle | None,
        actual_new_bytes: int,
        extra_reservations: list[StorageReservation],
    ) -> tuple[AssetReference, int]:
        digest, size_bytes = compute_file_sha256(src_path)
        self._check_object_size_limit(size_bytes)

        if self._dedup is not None:
            will_dedup = False
            if self._ledger is not None:
                existing = await self._ledger.find_active_by_checksum(digest, zone=zone)
                if existing is not None and await self._storage.exists(existing.object_key):
                    will_dedup = True
            if not will_dedup and reservation_handle is not None:
                await self._ensure_reservation_headroom(
                    needed_bytes=size_bytes,
                    already_reserved_bytes=reservation_handle.reservation.reserved_bytes,
                    actual_new_bytes=actual_new_bytes,
                    zone=zone,
                    job_id=job_id,
                    extra_reservations=extra_reservations,
                    now=now,
                )
            link = AssetReferenceLink(
                object_key=object_key,
                ref_kind=ref_kind,
                ref_owner_id=ref_owner_id,
                asset_id=asset.asset_id,
                provider=dataset.provider,
                product=dataset.product,
                created_at=now,
                metadata={"dataset_id": str(dataset.dataset_id), "job_id": job_id},
            )
            stored = await self._dedup.store_or_deduplicate_file(
                source_path=src_path,
                zone=zone,
                object_key=object_key,
                ref=link,
                media_type=asset.media_type,
                data_format=asset.data_format,
                original_size_bytes=original_size_bytes,
                compression_codec=compression_codec,
                verify_sha256=asset.checksum_sha256,
                now=now,
            )
            persisted = AssetReference(
                asset_id=stored.record.object_key,
                uri=self._asset_storage_uri(stored.record.object_key),
                data_format=asset.data_format,
                media_type=asset.media_type,
                checksum_sha256=stored.record.content_sha256,
                size_bytes=stored.record.size_bytes,
                storage_key=stored.record.object_key,
                zone=zone,
            )
            delta = 0 if stored.deduplicated else stored.record.size_bytes
            return persisted, delta

        if reservation_handle is not None:
            await self._ensure_reservation_headroom(
                needed_bytes=size_bytes,
                already_reserved_bytes=reservation_handle.reservation.reserved_bytes,
                actual_new_bytes=actual_new_bytes,
                zone=zone,
                job_id=job_id,
                extra_reservations=extra_reservations,
                now=now,
            )
        raw_persisted = await self._storage.put_file(object_key, src_path, asset.media_type)
        persisted = replace(
            raw_persisted,
            storage_key=raw_persisted.storage_key or object_key,
            zone=zone,
        )
        return persisted, (persisted.size_bytes or size_bytes)

    async def _persist_raw_assets(
        self,
        dataset: SpatialDataset,
        scratch_dir: Path,
        *,
        job_id: str,
        now: datetime,
        reservation_handle: ReservationHandle | None,
        actual_new_bytes: int,
        extra_reservations: list[StorageReservation],
    ) -> tuple[SpatialDataset, dict[str, Path], int]:
        stored_assets: list[AssetReference] = []
        local_paths: dict[str, Path] = {}
        added_bytes = 0
        for idx, asset in enumerate(dataset.assets):
            src_path = _local_asset_path(asset)
            if src_path is not None and src_path.is_file():
                digest, _ = compute_file_sha256(src_path)
                key = (
                    self._zones.raw_key(
                        dataset.provider,
                        dataset.product,
                        str(dataset.dataset_id),
                        src_path.name,
                        content_sha256=digest,
                    )
                    if self._zones is not None
                    else f"raw/{dataset.dataset_id}/{idx}_{src_path.name}"
                )
                persisted, delta = await self._persist_zone_file(
                    zone="raw",
                    object_key=key,
                    src_path=src_path,
                    asset=asset,
                    ref_kind="dataset",
                    ref_owner_id=str(dataset.dataset_id),
                    dataset=dataset,
                    now=now,
                    original_size_bytes=None,
                    compression_codec="none",
                    job_id=job_id,
                    reservation_handle=reservation_handle,
                    actual_new_bytes=actual_new_bytes + added_bytes,
                    extra_reservations=extra_reservations,
                )
                added_bytes += delta
                stored_assets.append(persisted)
                local_paths[persisted.asset_id] = src_path
            elif await self._storage.exists(asset.asset_id):
                dest = scratch_dir / "raw" / f"{idx}_{Path(asset.asset_id).name}"
                await self._storage.stream_to_path(asset.asset_id, dest)
                stored_assets.append(asset)
                local_paths[asset.asset_id] = dest
            else:
                stored_assets.append(asset)
        return replace(dataset, assets=tuple(stored_assets)), local_paths, added_bytes

    async def _persist_derived_assets(
        self,
        dataset: SpatialDataset,
        *,
        job_id: str,
        now: datetime,
        reservation_handle: ReservationHandle | None,
        actual_new_bytes: int,
        extra_reservations: list[StorageReservation],
    ) -> tuple[SpatialDataset, int]:
        persisted_assets: list[AssetReference] = []
        added_bytes = 0
        cumulative_output_bytes = 0
        comp_policy = self._compression.policy
        for idx, asset in enumerate(dataset.assets):
            local_path = _local_asset_path(asset)
            if local_path is not None and local_path.is_file():
                digest, size_bytes = compute_file_sha256(local_path)
                self._check_object_size_limit(size_bytes)
                cumulative_output_bytes += size_bytes
                if (
                    self._settings is not None
                    and cumulative_output_bytes > self._settings.ghs_storage_max_job_output_bytes
                ):
                    raise ObjectTooLargeError(
                        f"Derived job output total {cumulative_output_bytes} B exceeds cap "
                        f"{self._settings.ghs_storage_max_job_output_bytes} B",
                        requested_bytes=cumulative_output_bytes,
                        limit_bytes=self._settings.ghs_storage_max_job_output_bytes,
                        scope="job_output",
                    )

                key = (
                    self._zones.derived_key(
                        str(dataset.dataset_id),
                        local_path.name,
                        product=dataset.product,
                        content_sha256=digest,
                    )
                    if self._zones is not None
                    else f"derived/{dataset.dataset_id}/{idx}_{local_path.name}"
                )
                codec: CompressionCodec = "none"
                original_bytes: int | None = None
                if asset.data_format == "geotiff" and comp_policy.enabled:
                    codec = comp_policy.raster_codec
                    raw_pixels = _estimate_uncompressed_raster_bytes(dataset, local_path)
                    if raw_pixels is not None:
                        original_bytes = max(size_bytes, raw_pixels)

                persisted, delta = await self._persist_zone_file(
                    zone="derived",
                    object_key=key,
                    src_path=local_path,
                    asset=asset,
                    ref_kind="job",
                    ref_owner_id=job_id,
                    dataset=dataset,
                    now=now,
                    original_size_bytes=original_bytes,
                    compression_codec=codec,
                    job_id=job_id,
                    reservation_handle=reservation_handle,
                    actual_new_bytes=actual_new_bytes + added_bytes,
                    extra_reservations=extra_reservations,
                )
                added_bytes += delta
                persisted_assets.append(persisted)
            else:
                persisted_assets.append(asset)
        return replace(dataset, assets=tuple(persisted_assets)), added_bytes

    def _run_spatial_transform(
        self,
        dataset: SpatialDataset,
        plan: HarmonizationPlan,
        target_grid: GridSpec,
        local_paths: dict[str, Path],
        out_dir: Path,
    ) -> tuple[SpatialDataset, QualityReport, tuple[str, ...]]:
        transformer = TargetGridTransformer(
            output_dir=out_dir,
            reader_registry=self._readers,
            asset_resolver=lambda a: local_paths[a.asset_id],
            compression_policy=self._compression.policy,
        )
        req = TargetGridTransformRequest(
            dataset=dataset,
            target_grid=target_grid,
            variables=plan.variables or None,
            resampling_policy=plan.resampling_policy,
            max_grid_pixels=self._max_grid_pixels,
        )
        transformed = transformer.transform(req)
        QualityValidator.enforce(transformed.quality_report)
        return transformed.dataset, transformed.quality_report, transformed.warnings

    def _validate_raw_dataset(
        self, dataset: SpatialDataset, local_paths: dict[str, Path]
    ) -> QualityReport:
        frac = dataset.quality_metadata.valid_observation_fraction
        if dataset.spatial_metadata.representation != "raster" and frac is not None:
            warnings: list[str] = []
            errors: list[str] = []
            if dataset.quality_metadata.excluded_count > 0:
                warnings.append(
                    f"Dataset records {dataset.quality_metadata.excluded_count} excluded"
                )
            if frac < self._quality_policy.min_valid_fraction or frac == 0.0:
                errors.append(
                    f"Valid observation fraction {frac:.4f} is below policy "
                    f"minimum {self._quality_policy.min_valid_fraction:.4f}"
                )
            return QualityValidator.enforce(
                QualityReport(
                    passed=not errors,
                    valid_fraction=frac,
                    nodata_fraction=max(0.0, 1.0 - frac),
                    checks=("metadata_integrity", "valid_observation_fraction"),
                    warnings=tuple(warnings),
                    errors=tuple(errors),
                )
            )

        validator = QualityValidator(
            policy=self._quality_policy,
            reader_registry=self._readers,
            asset_resolver=lambda a: local_paths[a.asset_id],
        )
        report = validator.validate_dataset_assets(dataset, already_scaled=False)
        return QualityValidator.enforce(report)

    async def execute_plan(
        self, plan: HarmonizationPlan, *, job_id: UUID | None = None
    ) -> ProcessingResult:
        """Execute a complete harmonization plan and persist outputs and provenance."""
        handler = self._handlers.get(plan.provider, plan.product)
        now = datetime.now(UTC)
        run_job_id = job_id or uuid4()
        job_owner_id = str(run_job_id)

        est_bytes = 0
        if self._quota is not None:
            if plan.target_grid is not None:
                est_bytes = self._quota.estimate_grid_output_bytes(
                    plan.target_grid,
                    variable_count=max(1, len(plan.variables)),
                )
            else:
                est_bytes = self._quota.estimate_upload_bytes()

        temp_base = self._ensure_temp_capacity(est_bytes)
        reserve_zone: StorageZone = "derived" if plan.target_grid is not None else "raw"
        reserve_op = "harmonize_grid" if plan.target_grid is not None else "ingest_raw"
        scope_cm: AbstractAsyncContextManager[ReservationHandle | None] = (
            self._quota.reservation_scope(
                estimated_bytes=est_bytes,
                zone=reserve_zone,
                operation=reserve_op,
                job_id=job_owner_id,
                now=now,
            )
            if self._quota is not None
            else nullcontext(None)
        )

        raw_dataset: SpatialDataset | None = None
        extra_reservations: list[StorageReservation] = []
        actual_new_bytes = 0
        try:
            async with scope_cm as res_handle:
                raw_dataset = await handler.handle_payload(plan.request_payload)
                source_lookup_id = raw_dataset.granule_id or raw_dataset.source_id
                existing_source = await self._datasets.find_by_source(
                    plan.provider, plan.product, source_lookup_id
                )
                extra_warnings: list[str] = []
                if existing_source is not None:
                    extra_warnings.append(
                        f"Source observation '{source_lookup_id}' matches previously ingested "
                        f"dataset {existing_source.dataset_id}; raw assets deduplicated "
                        "against ledger."
                    )
                with tempfile.TemporaryDirectory(prefix="ghs-exec-", dir=temp_base) as tmp_root:
                    scratch = Path(tmp_root)
                    staged_ds, local_paths, raw_delta = await self._persist_raw_assets(
                        raw_dataset,
                        scratch,
                        job_id=job_owner_id,
                        now=now,
                        reservation_handle=res_handle,
                        actual_new_bytes=actual_new_bytes,
                        extra_reservations=extra_reservations,
                    )
                    actual_new_bytes += raw_delta

                    warnings: tuple[str, ...] = ()
                    if plan.target_grid is not None:
                        derived_ds, qc_report, warnings = await asyncio.to_thread(
                            self._run_spatial_transform,
                            staged_ds,
                            plan,
                            plan.target_grid,
                            local_paths,
                            scratch / "out",
                        )
                        final_ds, derived_delta = await self._persist_derived_assets(
                            derived_ds,
                            job_id=job_owner_id,
                            now=now,
                            reservation_handle=res_handle,
                            actual_new_bytes=actual_new_bytes,
                            extra_reservations=extra_reservations,
                        )
                        actual_new_bytes += derived_delta
                    else:
                        qc_report = await asyncio.to_thread(
                            self._validate_raw_dataset, staged_ds, local_paths
                        )
                        final_ds = staged_ds
                    warnings = (*extra_warnings, *warnings)

                await self._datasets.save(final_ds)

                if self._ledger is not None and plan.target_grid is not None:
                    done_now = datetime.now(UTC)
                    for asset in final_ds.assets:
                        await self._ledger.add_asset_reference(
                            AssetReferenceLink(
                                object_key=asset.asset_id,
                                ref_kind="dataset",
                                ref_owner_id=str(final_ds.dataset_id),
                                asset_id=asset.asset_id,
                                provider=final_ds.provider,
                                product=final_ds.product,
                                created_at=done_now,
                                metadata={"job_id": job_owner_id},
                            ),
                            done_now,
                        )

                if self._lifecycle is not None:
                    await self._lifecycle.on_job_completed(
                        job_owner_id, success=True, now=datetime.now(UTC)
                    )

                if res_handle is not None:
                    base_reserved = res_handle.reservation.reserved_bytes
                    res_handle.actual_bytes = min(actual_new_bytes, base_reserved)
                    remaining_actual = max(0, actual_new_bytes - base_reserved)
                    commit_now = datetime.now(UTC)
                    for extra in extra_reservations:
                        if self._quota is not None:
                            alloc = min(remaining_actual, extra.reserved_bytes)
                            await self._quota.commit_reservation(
                                extra.reservation_id, actual_bytes=alloc, now=commit_now
                            )
                            remaining_actual = max(0, remaining_actual - alloc)
                    extra_reservations.clear()

            logger.info(
                "Persisted harmonized dataset %s (%s/%s)",
                final_ds.dataset_id,
                plan.provider,
                plan.product,
            )
            return ProcessingResult(
                job_id=run_job_id,
                dataset=final_ds,
                quality_report=qc_report,
                completed_at=datetime.now(UTC),
                output_assets=final_ds.assets,
                warnings=warnings,
            )
        except Exception:
            if extra_reservations and self._quota is not None:
                fail_now = datetime.now(UTC)
                for extra in extra_reservations:
                    try:
                        await self._quota.release_reservation(
                            extra.reservation_id,
                            status="failed",
                            now=fail_now,
                            reason="execution_failed",
                        )
                    except Exception:
                        logger.warning(
                            "Failed releasing overflow reservation %s", extra.reservation_id
                        )
            if self._lifecycle is not None:
                try:
                    await self._lifecycle.on_job_completed(
                        job_owner_id, success=False, now=datetime.now(UTC)
                    )
                except Exception:
                    logger.warning("Failed lifecycle cleanup for job %s after error", job_owner_id)
            raise
        finally:
            self._cleanup_handler_temp_dirs(raw_dataset, temp_base)
