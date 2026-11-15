"""Application use-case orchestration for Scientific Assessments."""

import asyncio
import json
import logging
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from terra_scientific import (
    DEFAULT_METHOD_REGISTRY,
    ReadinessAssessmentReport,
    ScientificAssessmentService,
    evaluate_assessment_readiness,
)
from terra_scientific.adapters.ghs import LocalArtifactDatasetLoader, map_ghs_dataset_payload
from terra_scientific.domain.exceptions import ScientificCoreError, ScientificInputError
from terra_scientific.domain.models.dataset import ScientificDataset, ScientificGridStack
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.methods.registry import MethodSpec
from terra_scientific.sources.catalog import assert_quantitative_source_allowed

from terra.infrastructure.object_storage import ObjectStoragePort
from terra.modules.assessments.domain.entities import (
    AssessmentLifecycleStatus,
    ScientificAssessment,
)
from terra.modules.assessments.domain.exceptions import (
    AssessmentAccessDeniedError,
    AssessmentNotFoundError,
    AssessmentRegionAccessDeniedError,
    AssessmentRegionNotFoundError,
    AssessmentValidationError,
)
from terra.modules.assessments.domain.ports import GhsDatasetClient
from terra.modules.assessments.domain.repositories import AssessmentRepository
from terra.modules.regions.domain.repositories import RegionRepository

logger = logging.getLogger(__name__)


def _parse_inline_dataset(raw: dict[str, Any]) -> ScientificDataset:
    if "spatial_support" in raw and "temporal_metadata" in raw:
        dataset = ScientificDataset.model_validate(raw)
    else:
        dataset = map_ghs_dataset_payload(raw)
    assert_quantitative_source_allowed(dataset.source_id)
    return dataset


class AssessmentApplicationService:
    """Orchestrates assessment validation, persistence, GHS fetch, and Scientific Core runs."""

    def __init__(
        self,
        repo: AssessmentRepository,
        region_repo: RegionRepository,
        ghs_client: GhsDatasetClient,
        artifact_root: str | None = None,
        scientific_service: ScientificAssessmentService | None = None,
        object_storage: ObjectStoragePort | None = None,
        presign_ttl_seconds: int = 300,
    ) -> None:
        self._repo = repo
        self._region_repo = region_repo
        self._ghs_client = ghs_client
        self._artifact_root = Path(artifact_root).resolve() if artifact_root else None
        self._scientific_service = scientific_service or ScientificAssessmentService()
        self._object_storage = object_storage
        self._presign_ttl_seconds = max(30, min(3600, presign_ttl_seconds))

    def list_methods(self) -> list[MethodSpec]:
        """Return all cataloged scientific methods (implemented P0/P1 and deferred P2)."""
        return DEFAULT_METHOD_REGISTRY.list_all()

    async def create_assessment(
        self,
        *,
        owner_id: UUID,
        title: str,
        region_id: UUID | None,
        execute_now: bool,
        request_config: dict[str, Any],
        ghs_dataset_ids: list[str],
        inline_datasets: list[dict[str, Any]],
    ) -> ScientificAssessment:
        """Validate inputs, persist an assessment, and optionally execute immediately."""
        cleaned_title = title.strip()
        if not cleaned_title:
            raise AssessmentValidationError("Assessment title cannot be blank.")

        dedup_ghs_ids = list(dict.fromkeys(id_.strip() for id_ in ghs_dataset_ids if id_.strip()))
        if not dedup_ghs_ids and not inline_datasets:
            raise AssessmentValidationError(
                "Assessment requires at least one GHS dataset ID or inline dataset."
            )

        config_copy = dict(request_config)
        if region_id is not None:
            region = await self._region_repo.get_by_id(region_id)
            if region is None:
                raise AssessmentRegionNotFoundError(f"Region {region_id} not found")
            if region.owner_id != owner_id:
                raise AssessmentRegionAccessDeniedError("You do not own the referenced region")
            config_copy.setdefault("region_id", str(region.id))
            config_copy.setdefault("region_name", region.name)
            config_copy.setdefault("region_area_km2", region.metrics.approx_area_km2)

        assessment_id = uuid4()
        self._validate_request_and_inline_inputs(
            assessment_id=assessment_id,
            request_config=config_copy,
            inline_datasets=inline_datasets,
        )

        now = datetime.now(UTC)
        entity = ScientificAssessment(
            id=assessment_id,
            owner_id=owner_id,
            region_id=region_id,
            title=cleaned_title,
            status="queued",
            request_config=config_copy,
            ghs_dataset_ids=dedup_ghs_ids,
            inline_datasets=list(inline_datasets),
            created_at=now,
            updated_at=now,
        )
        created = await self._repo.create(entity)
        if execute_now:
            return await self._execute_entity(created)
        return created

    async def evaluate_readiness(
        self,
        *,
        owner_id: UUID,
        region_id: UUID | None,
        request_config: dict[str, Any],
        ghs_dataset_ids: list[str],
        inline_datasets: list[dict[str, Any]],
    ) -> ReadinessAssessmentReport:
        """Evaluate adaptive source- and method-specific readiness before execution."""
        config_copy = dict(request_config)
        config_copy.setdefault("request_id", "readiness-preview")
        if region_id is not None:
            region = await self._region_repo.get_by_id(region_id)
            if region is None:
                raise AssessmentRegionNotFoundError(f"Region {region_id} not found")
            if region.owner_id != owner_id:
                raise AssessmentRegionAccessDeniedError("You do not own the referenced region")
            config_copy.setdefault("region_id", str(region.id))
            config_copy.setdefault("region_name", region.name)
            config_copy.setdefault("region_area_km2", region.metrics.approx_area_km2)

        dedup_ghs_ids = list(dict.fromkeys(str(item).strip() for item in ghs_dataset_ids if item))
        sci_request = self._validate_request_and_inline_inputs(
            assessment_id=uuid4(),
            request_config=config_copy,
            inline_datasets=inline_datasets,
        )

        datasets: list[ScientificDataset] = []
        try:
            for ghs_id in dedup_ghs_ids:
                datasets.append(await self._ghs_client.fetch_dataset(ghs_id))

            for raw_ds in inline_datasets:
                if "spatial_support" in raw_ds and "temporal_metadata" in raw_ds:
                    datasets.append(ScientificDataset.model_validate(raw_ds))
                else:
                    datasets.append(map_ghs_dataset_payload(raw_ds))

            for ds in datasets:
                assert_quantitative_source_allowed(ds.source_id, ds.product)
        except (ScientificCoreError, ScientificInputError, ValidationError, ValueError) as exc:
            raise AssessmentValidationError(str(exc)) from exc

        return evaluate_assessment_readiness(sci_request, datasets=datasets)

    def _validate_request_and_inline_inputs(
        self,
        *,
        assessment_id: UUID,
        request_config: dict[str, Any],
        inline_datasets: list[dict[str, Any]],
    ) -> AssessmentRequest:
        raw_out_dir = request_config.get("output_artifact_dir")
        if raw_out_dir is not None:
            if self._artifact_root is None:
                raise AssessmentValidationError(
                    "output_artifact_dir is not enabled on this server instance."
                )
            resolved_out = Path(str(raw_out_dir)).resolve()
            if not resolved_out.is_relative_to(self._artifact_root):
                raise AssessmentValidationError(
                    "output_artifact_dir must remain inside configured scientific_artifact_dir."
                )

        try:
            validated_req = AssessmentRequest.model_validate(
                {
                    **request_config,
                    "request_id": request_config.get("request_id", str(assessment_id)),
                }
            )
            for raw_ds in inline_datasets:
                _parse_inline_dataset(raw_ds)
        except (ValidationError, ScientificCoreError, TypeError, ValueError, KeyError) as exc:
            raise AssessmentValidationError(str(exc)) from exc
        return validated_req

    async def get_assessment(self, owner_id: UUID, assessment_id: UUID) -> ScientificAssessment:
        """Retrieve a single assessment owned by the authenticated user."""
        assessment = await self._repo.get_by_id(assessment_id)
        if assessment is None:
            raise AssessmentNotFoundError(f"Assessment {assessment_id} not found")
        if assessment.owner_id != owner_id:
            raise AssessmentAccessDeniedError("You do not have access to this assessment")
        return assessment

    async def list_assessments(self, owner_id: UUID) -> list[ScientificAssessment]:
        """List all assessments created by the authenticated user."""
        return await self._repo.list_by_owner(owner_id)

    async def execute_assessment(self, owner_id: UUID, assessment_id: UUID) -> ScientificAssessment:
        """Execute a persisted queued or failed assessment after verifying ownership."""
        entity = await self.get_assessment(owner_id, assessment_id)
        if entity.status == "running":
            raise AssessmentValidationError("Assessment is already executing.")
        running = await self._repo.update(
            replace(entity, status="running", error_message=None, updated_at=datetime.now(UTC))
        )
        return await self._execute_entity(running)

    async def execute_claimed_assessment(
        self, assessment: ScientificAssessment
    ) -> ScientificAssessment:
        """Execute an already-claimed assessment inside the worker runtime."""
        return await self._execute_entity(assessment)

    async def _execute_entity(self, entity: ScientificAssessment) -> ScientificAssessment:
        try:
            config_copy = dict(entity.request_config)
            if self._artifact_root is not None and "output_artifact_dir" not in config_copy:
                config_copy["output_artifact_dir"] = str(self._artifact_root / str(entity.id))

            req = self._validate_request_and_inline_inputs(
                assessment_id=entity.id,
                request_config=config_copy,
                inline_datasets=entity.inline_datasets,
            )

            datasets: list[ScientificDataset] = [
                _parse_inline_dataset(raw) for raw in entity.inline_datasets
            ]
            for ghs_id in entity.ghs_dataset_ids:
                ghs_ds = await self._ghs_client.fetch_dataset(ghs_id)
                assert_quantitative_source_allowed(ghs_ds.source_id)
                datasets.append(ghs_ds)

            grid_stacks = await self._load_grid_stacks(datasets)

            result = await asyncio.to_thread(
                self._scientific_service.run_assessment,
                req,
                datasets=datasets,
                grid_stacks=grid_stacks or None,
                assessment_id=str(entity.id),
            )
            publish_derived = config_copy.get("publish_derived_spatial_artifacts", True)
            published_artifacts = (
                await self._publish_derived_spatial_artifacts(
                    entity=entity,
                    datasets=datasets,
                    result=result,
                )
                if publish_derived is not False
                else {}
            )
            now = datetime.now(UTC)
            result_payload_dict = result.model_dump(mode="json")
            merged_artifacts = dict(result.artifact_manifest)
            merged_artifacts.update(published_artifacts)
            stored_artifacts = await self._store_assessment_artifacts(
                entity=entity,
                datasets=datasets,
                result_payload=result_payload_dict,
                result_status=result.status.value,
                method_version=getattr(result, "method_version", "1.0.0"),
                executed_at=now,
                local_manifest=dict(result.artifact_manifest),
                published_artifacts=published_artifacts,
            )
            merged_artifacts.update(stored_artifacts)
            updated = replace(
                entity,
                status=cast(AssessmentLifecycleStatus, result.status.value),
                result_payload=result_payload_dict,
                artifact_paths=merged_artifacts,
                error_message=None,
                updated_at=now,
                completed_at=now,
            )
            return await self._repo.update(updated)
        except Exception as exc:
            now = datetime.now(UTC)
            failed = replace(
                entity,
                status="failed",
                error_message=str(exc),
                updated_at=now,
            )
            await self._repo.update(failed)
            if isinstance(exc, (ScientificCoreError, ScientificInputError, TypeError, ValueError)):
                raise AssessmentValidationError(str(exc)) from exc
            raise

    async def _load_grid_stacks(
        self,
        datasets: list[ScientificDataset],
    ) -> dict[str, ScientificGridStack]:
        stacks: dict[str, ScientificGridStack] = {}
        loader = LocalArtifactDatasetLoader()
        download_fn = getattr(self._ghs_client, "download_dataset_asset", None)
        with tempfile.TemporaryDirectory(prefix="terra-ghs-grid-") as tmp_dir:
            tmp_root = Path(tmp_dir)
            for ds_idx, ds in enumerate(datasets):
                for var_name in ds.raster_refs:
                    if var_name in ds.series:
                        continue
                    target_ds = ds
                    ref_value = ds.raster_refs[var_name]
                    ref_path = Path(ref_value)
                    is_local_artifact = ref_path.is_file() and ref_path.suffix.lower() in {
                        ".npz",
                        ".tif",
                        ".tiff",
                    }
                    if ds.ghs_dataset_id is not None and not is_local_artifact:
                        if not callable(download_fn):
                            continue
                        try:
                            downloaded_path = await download_fn(
                                ds.ghs_dataset_id,
                                tmp_root / f"ds_{ds_idx}",
                                filename_hint=Path(ref_value).name or f"{ds.ghs_dataset_id}.tif",
                            )
                        except Exception as exc:
                            logger.warning(
                                "Skipping remote raster asset %s for GHS dataset %s: %s",
                                var_name,
                                ds.ghs_dataset_id,
                                exc,
                            )
                            continue
                        if not isinstance(downloaded_path, Path) or not downloaded_path.is_file():
                            continue
                        target_ds = ds.model_copy(
                            update={
                                "raster_refs": {**ds.raster_refs, var_name: str(downloaded_path)}
                            }
                        )
                    stack = loader.load_grid_stack(target_ds, var_name)
                    if stack is not None:
                        stacks[f"{ds.dataset_id}:{var_name}"] = stack
        return stacks

    async def _store_assessment_artifacts(
        self,
        *,
        entity: ScientificAssessment,
        datasets: list[ScientificDataset],
        result_payload: dict[str, Any],
        result_status: str,
        method_version: str,
        executed_at: datetime,
        local_manifest: dict[str, str],
        published_artifacts: dict[str, str],
    ) -> dict[str, str]:
        if self._object_storage is None:
            return {}

        result_bytes = json.dumps(result_payload, indent=2, sort_keys=True).encode("utf-8")
        result_key = f"assessments/{entity.id}/result.json"
        result_desc = await self._object_storage.put_bytes(
            result_key,
            result_bytes,
            content_type="application/json",
            metadata={"assessment_id": str(entity.id), "owner_id": str(entity.owner_id)},
        )

        provenance_payload = {
            "assessment_id": str(entity.id),
            "owner_id": str(entity.owner_id),
            "region_id": str(entity.region_id) if entity.region_id else None,
            "title": entity.title,
            "status": result_status,
            "method_version": method_version,
            "executed_at": executed_at.isoformat(),
            "ghs_dataset_ids": list(entity.ghs_dataset_ids),
            "datasets": [
                {
                    "dataset_id": ds.dataset_id,
                    "ghs_dataset_id": ds.ghs_dataset_id,
                    "source_id": ds.source_id,
                    "variables": list(ds.series.keys()) or list(ds.raster_refs.keys()),
                }
                for ds in datasets
            ],
            "published_ghs_datasets": published_artifacts,
            "local_artifact_manifest": local_manifest,
        }
        provenance_bytes = json.dumps(provenance_payload, indent=2, sort_keys=True).encode("utf-8")
        provenance_key = f"assessments/{entity.id}/provenance.json"
        provenance_desc = await self._object_storage.put_bytes(
            provenance_key,
            provenance_bytes,
            content_type="application/json",
            metadata={"assessment_id": str(entity.id), "owner_id": str(entity.owner_id)},
        )

        return {
            "object_storage_backend": self._object_storage.backend_name,
            "result_object_key": result_desc.key,
            "result_object_sha256": result_desc.checksum_sha256 or "",
            "provenance_object_key": provenance_desc.key,
            "provenance_object_sha256": provenance_desc.checksum_sha256 or "",
        }

    async def _publish_derived_spatial_artifacts(
        self,
        *,
        entity: ScientificAssessment,
        datasets: list[ScientificDataset],
        result: Any,
    ) -> dict[str, str]:
        publish_fn = getattr(self._ghs_client, "publish_derived_dataset", None)
        if not callable(publish_fn):
            return {}

        bbox_wgs84: tuple[float, float, float, float] | None = None
        aoi_geojson: dict[str, Any] | None = None
        if entity.region_id is not None:
            region = await self._region_repo.get_by_id(entity.region_id)
            if region is not None:
                bbox_wgs84 = region.metrics.bbox
                aoi_geojson = region.geometry

        if bbox_wgs84 is None:
            for ds in datasets:
                if ds.spatial_support.bounds is not None and "4326" in (
                    ds.spatial_support.crs or ""
                ):
                    bbox_wgs84 = ds.spatial_support.bounds
                    break

        if bbox_wgs84 is None:
            return {}

        source_ids = [
            ds.ghs_dataset_id for ds in datasets if getattr(ds, "ghs_dataset_id", None) is not None
        ]
        temporal_start: str | None = None
        temporal_end: str | None = None
        for ds in datasets:
            tm = getattr(ds, "temporal_metadata", None)
            if tm is not None:
                if tm.start is not None:
                    temporal_start = tm.start.isoformat()
                if tm.end is not None:
                    temporal_end = tm.end.isoformat()
                if temporal_start and temporal_end:
                    break

        requests_to_publish: list[dict[str, object]] = []

        for anom in getattr(result, "anomalies", []):
            var_lower = anom.variable_name.lower()
            product: str | None = None
            out_var = "zscore"
            if "ndvi" in var_lower:
                product = "TERRA-NDVI-ANOM"
                out_var = "ndvi_zscore"
            elif "evi" in var_lower:
                product = "TERRA-EVI-ANOM"
                out_var = "evi_zscore"
            elif "lst" in var_lower or "temp" in var_lower:
                product = "TERRA-LST-ANOM"
                out_var = "lst_zscore"
            finite_z = [float(v) for v in anom.standard_zscores if v is not None]
            if product is None or not finite_z:
                continue
            requests_to_publish.append(
                {
                    "product": product,
                    "variable_name": out_var,
                    "units": "z-score",
                    "bbox_wgs84": list(bbox_wgs84),
                    "scope": "aoi",
                    "scalar_value": finite_z[-1],
                    "aoi_geojson": aoi_geojson,
                    "temporal_start": temporal_start,
                    "temporal_end": temporal_end,
                    "timestamps": [t.isoformat() for t in anom.timestamps],
                    "time_series_values": [
                        None if v is None else float(v) for v in anom.standard_zscores
                    ],
                    "source_dataset_ids": source_ids,
                    "method_version": getattr(result, "method_version", "1.0.0"),
                }
            )

        for trend in getattr(result, "trends", []):
            if trend.sens_slope is not None:
                slope_unit = trend.slope_unit or "unit/step"
                requests_to_publish.append(
                    {
                        "product": "TERRA-SEN-SLOPE",
                        "variable_name": "sens_slope",
                        "units": slope_unit,
                        "bbox_wgs84": list(bbox_wgs84),
                        "scope": "aoi",
                        "scalar_value": float(trend.sens_slope),
                        "aoi_geojson": aoi_geojson,
                        "temporal_start": temporal_start,
                        "temporal_end": temporal_end,
                        "source_dataset_ids": source_ids,
                        "method_version": getattr(result, "method_version", "1.0.0"),
                    }
                )
                if "ndvi" in trend.variable_name.lower() or "evi" in trend.variable_name.lower():
                    requests_to_publish.append(
                        {
                            "product": "TERRA-VEG-TREND",
                            "variable_name": "vegetation_trend",
                            "units": slope_unit,
                            "bbox_wgs84": list(bbox_wgs84),
                            "scope": "aoi",
                            "scalar_value": float(trend.sens_slope),
                            "aoi_geojson": aoi_geojson,
                            "temporal_start": temporal_start,
                            "temporal_end": temporal_end,
                            "source_dataset_ids": source_ids,
                            "method_version": getattr(result, "method_version", "1.0.0"),
                        }
                    )
            p_val = trend.adjusted_p_value if trend.adjusted_p_value is not None else trend.p_value
            if p_val is not None:
                requests_to_publish.append(
                    {
                        "product": "TERRA-MK-TEST",
                        "variable_name": "mk_adjusted_pvalue",
                        "units": "p-value",
                        "bbox_wgs84": list(bbox_wgs84),
                        "scope": "aoi",
                        "scalar_value": float(p_val),
                        "aoi_geojson": aoi_geojson,
                        "temporal_start": temporal_start,
                        "temporal_end": temporal_end,
                        "source_dataset_ids": source_ids,
                        "method_version": getattr(result, "method_version", "1.0.0"),
                    }
                )

        resilience_mapping = (
            ("resistance", "TERRA-RES-RESISTANCE", "resistance_index"),
            ("recovery", "TERRA-RES-RECOVERY", "recovery_index"),
            ("stability", "TERRA-RES-STABILITY", "stability_index"),
            ("sensitivity", "TERRA-RES-SENSITIVITY", "sensitivity_index"),
        )
        for res in getattr(result, "resilience", []):
            for attr_name, product, var_name in resilience_mapping:
                metric = getattr(res, attr_name, None)
                if metric is not None and metric.available and metric.value is not None:
                    requests_to_publish.append(
                        {
                            "product": product,
                            "variable_name": var_name,
                            "units": metric.unit or "index",
                            "bbox_wgs84": list(bbox_wgs84),
                            "scope": "aoi",
                            "scalar_value": float(metric.value),
                            "aoi_geojson": aoi_geojson,
                            "temporal_start": temporal_start,
                            "temporal_end": temporal_end,
                            "source_dataset_ids": source_ids,
                            "method_version": getattr(result, "method_version", "1.0.0"),
                        }
                    )

        published: dict[str, str] = {}
        for payload in requests_to_publish:
            product_name = str(payload["product"])
            try:
                resp = await publish_fn(payload)
                if isinstance(resp, dict) and resp.get("dataset_id"):
                    published[f"ghs_derived:{product_name}"] = str(resp["dataset_id"])
            except Exception as exc:
                logger.warning("Failed to publish derived dataset %s to GHS: %s", product_name, exc)
        return published

    async def compare_assessments(
        self,
        owner_id: UUID,
        primary_id: UUID,
        comparison_id: UUID,
    ) -> Any:
        """Compare two completed user assessments across shared environmental variables."""
        from terra.modules.assessments.application.comparison import (
            COMPLETED_STATUSES,
            build_assessment_comparison,
        )

        if primary_id == comparison_id:
            raise AssessmentValidationError(
                "Select two distinct assessments to perform a comparison."
            )

        primary = await self.get_assessment(owner_id, primary_id)
        comparison = await self.get_assessment(owner_id, comparison_id)

        if str(primary.status) not in COMPLETED_STATUSES or primary.result_payload is None:
            raise AssessmentValidationError(
                f"Primary assessment {primary_id} has not completed with scientific results."
            )
        if str(comparison.status) not in COMPLETED_STATUSES or comparison.result_payload is None:
            raise AssessmentValidationError(
                f"Comparison assessment {comparison_id} has not completed with scientific results."
            )

        return build_assessment_comparison(primary, comparison)

    async def list_assessment_artifacts(
        self,
        owner_id: UUID,
        assessment_id: UUID,
    ) -> list[dict[str, Any]]:
        """List stored result and provenance artifacts with presigned R2 URLs when available."""
        assessment = await self.get_assessment(owner_id, assessment_id)
        candidates = (
            ("result.json", "result_object_key", "result_object_sha256", "application/json"),
            (
                "provenance.json",
                "provenance_object_key",
                "provenance_object_sha256",
                "application/json",
            ),
        )
        items: list[dict[str, Any]] = []
        for name, key_field, sha_field, content_type in candidates:
            obj_key = assessment.artifact_paths.get(key_field)
            if not obj_key or self._object_storage is None:
                continue
            head = await self._object_storage.head_object(obj_key)
            if head is None:
                continue
            filename = f"assessment-{assessment.id}-{name}"
            presigned_url = await self._object_storage.generate_presigned_download_url(
                obj_key,
                expires_in=self._presign_ttl_seconds,
                filename=filename,
                content_type=content_type,
            )
            items.append(
                {
                    "name": name,
                    "object_key": obj_key,
                    "content_type": content_type,
                    "size_bytes": head.size_bytes,
                    "checksum_sha256": assessment.artifact_paths.get(sha_field)
                    or head.checksum_sha256,
                    "storage_backend": self._object_storage.backend_name,
                    "download_path": f"/api/v1/assessments/{assessment.id}/artifacts/{name}",
                    "presigned_url": presigned_url,
                    "presigned": presigned_url is not None,
                }
            )

        if not items and assessment.result_payload is not None:
            fallback_bytes = json.dumps(assessment.result_payload, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            items.append(
                {
                    "name": "result.json",
                    "object_key": assessment.artifact_paths.get("assessment_result_json", "inline"),
                    "content_type": "application/json",
                    "size_bytes": len(fallback_bytes),
                    "checksum_sha256": assessment.artifact_paths.get("assessment_result_sha256"),
                    "storage_backend": self._object_storage.backend_name
                    if self._object_storage is not None
                    else "local",
                    "download_path": f"/api/v1/assessments/{assessment.id}/artifacts/result.json",
                    "presigned_url": None,
                    "presigned": False,
                }
            )
        return items

    async def download_assessment_artifact(
        self,
        owner_id: UUID,
        assessment_id: UUID,
        artifact_name: str,
    ) -> tuple[str, str, bytes]:
        """Download bytes for an allowlisted assessment artifact after ownership verification."""
        allowed = {
            "result.json": ("result_object_key", "application/json"),
            "provenance.json": ("provenance_object_key", "application/json"),
        }
        spec = allowed.get(artifact_name)
        if spec is None:
            raise AssessmentNotFoundError(f"Unknown assessment artifact '{artifact_name}'")

        assessment = await self.get_assessment(owner_id, assessment_id)
        key_field, content_type = spec
        obj_key = assessment.artifact_paths.get(key_field)
        filename = f"assessment-{assessment.id}-{artifact_name}"

        if obj_key and self._object_storage is not None:
            try:
                data = await self._object_storage.get_bytes(obj_key)
                return filename, content_type, data
            except FileNotFoundError:
                pass

        if artifact_name == "result.json" and assessment.result_payload is not None:
            data = json.dumps(assessment.result_payload, indent=2, sort_keys=True).encode("utf-8")
            return filename, content_type, data

        raise AssessmentNotFoundError(
            f"Artifact '{artifact_name}' is not available for assessment {assessment_id}"
        )
