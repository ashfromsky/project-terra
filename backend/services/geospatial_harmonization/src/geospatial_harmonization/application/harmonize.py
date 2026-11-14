"""Application orchestration pipeline connecting handlers, transformers, QC, and ports."""

import asyncio
import logging
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from geospatial_harmonization.domain.models.dataset import AssetReference, SpatialDataset
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.models.harmonization import (
    HarmonizationPlan,
    ProcessingResult,
    QualityReport,
    TargetGridTransformRequest,
)
from geospatial_harmonization.domain.ports import DatasetRepository, StoragePort
from geospatial_harmonization.handlers.registry import HandlerRegistry
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.transformations.quality import QualityPolicy, QualityValidator
from geospatial_harmonization.transformations.transformer import TargetGridTransformer

logger = logging.getLogger(__name__)


def _local_asset_path(asset: AssetReference) -> Path | None:
    parsed = urlparse(asset.uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme:
        return Path(asset.uri)
    return None


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
    ) -> None:
        self._handlers = handlers
        self._storage = storage
        self._datasets = datasets
        self._readers = readers or build_default_reader_registry()
        self._quality_policy = quality_policy or QualityPolicy()
        self._max_grid_pixels = max_grid_pixels

    async def _persist_raw_assets(
        self, dataset: SpatialDataset, scratch_dir: Path
    ) -> tuple[SpatialDataset, dict[str, Path]]:
        stored_assets: list[AssetReference] = []
        local_paths: dict[str, Path] = {}
        for idx, asset in enumerate(dataset.assets):
            src_path = _local_asset_path(asset)
            if src_path is not None and src_path.is_file():
                key = f"raw/{dataset.dataset_id}/{idx}_{src_path.name}"
                persisted = await self._storage.put_file(key, src_path, asset.media_type)
                stored_assets.append(persisted)
                local_paths[persisted.asset_id] = src_path
            elif await self._storage.exists(asset.asset_id):
                dest = scratch_dir / "raw" / f"{idx}_{Path(asset.asset_id).name}"
                await self._storage.materialize_to_path(asset.asset_id, dest)
                stored_assets.append(asset)
                local_paths[asset.asset_id] = dest
            else:
                stored_assets.append(asset)
        return replace(dataset, assets=tuple(stored_assets)), local_paths

    async def _persist_derived_assets(self, dataset: SpatialDataset) -> SpatialDataset:
        persisted_assets: list[AssetReference] = []
        for idx, asset in enumerate(dataset.assets):
            local_path = _local_asset_path(asset)
            if local_path is not None and local_path.is_file():
                key = f"derived/{dataset.dataset_id}/{idx}_{local_path.name}"
                persisted_assets.append(
                    await self._storage.put_file(key, local_path, asset.media_type)
                )
            else:
                persisted_assets.append(asset)
        return replace(dataset, assets=tuple(persisted_assets))

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
        raw_dataset = await handler.handle_payload(plan.request_payload)

        with tempfile.TemporaryDirectory(prefix="ghs-exec-") as tmp_root:
            scratch = Path(tmp_root)
            staged_ds, local_paths = await self._persist_raw_assets(raw_dataset, scratch)
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
                final_ds = await self._persist_derived_assets(derived_ds)
            else:
                qc_report = await asyncio.to_thread(
                    self._validate_raw_dataset, staged_ds, local_paths
                )
                final_ds = staged_ds

        await self._datasets.save(final_ds)
        logger.info(
            "Persisted harmonized dataset %s (%s/%s)",
            final_ds.dataset_id,
            plan.provider,
            plan.product,
        )
        return ProcessingResult(
            job_id=job_id or uuid4(),
            dataset=final_ds,
            quality_report=qc_report,
            completed_at=datetime.now(UTC),
            output_assets=final_ds.assets,
            warnings=warnings,
        )
