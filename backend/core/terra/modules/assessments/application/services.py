"""Application use-case orchestration for Scientific Assessments."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from terra_scientific import DEFAULT_METHOD_REGISTRY, ScientificAssessmentService
from terra_scientific.adapters.ghs import LocalArtifactDatasetLoader, map_ghs_dataset_payload
from terra_scientific.domain.exceptions import ScientificCoreError, ScientificInputError
from terra_scientific.domain.models.dataset import ScientificDataset, ScientificGridStack
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.methods.registry import MethodSpec
from terra_scientific.sources.catalog import assert_quantitative_source_allowed

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
    ) -> None:
        self._repo = repo
        self._region_repo = region_repo
        self._ghs_client = ghs_client
        self._artifact_root = Path(artifact_root).resolve() if artifact_root else None
        self._scientific_service = scientific_service or ScientificAssessmentService()

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

        if not ghs_dataset_ids and not inline_datasets:
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
            ghs_dataset_ids=list(ghs_dataset_ids),
            inline_datasets=list(inline_datasets),
            created_at=now,
            updated_at=now,
        )
        created = await self._repo.create(entity)
        if execute_now:
            return await self._execute_entity(created)
        return created

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
        except (ValidationError, ScientificCoreError, ValueError) as exc:
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

            grid_stacks = self._load_local_grid_stacks(datasets)

            result = await asyncio.to_thread(
                self._scientific_service.run_assessment,
                req,
                datasets=datasets,
                grid_stacks=grid_stacks or None,
                assessment_id=str(entity.id),
            )
            now = datetime.now(UTC)
            updated = replace(
                entity,
                status=cast(AssessmentLifecycleStatus, result.status.value),
                result_payload=result.model_dump(mode="json"),
                artifact_paths=dict(result.artifact_manifest),
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
            if isinstance(exc, ScientificInputError):
                raise AssessmentValidationError(str(exc)) from exc
            raise

    @staticmethod
    def _load_local_grid_stacks(
        datasets: list[ScientificDataset],
    ) -> dict[str, ScientificGridStack]:
        stacks: dict[str, ScientificGridStack] = {}
        loader = LocalArtifactDatasetLoader()
        for ds in datasets:
            for var_name in ds.raster_refs:
                if var_name in ds.series:
                    continue
                if ds.ghs_dataset_id is not None:
                    ref_path = Path(ds.raster_refs[var_name])
                    if not (
                        ref_path.is_file() and ref_path.suffix.lower() in {".npz", ".tif", ".tiff"}
                    ):
                        continue
                stack = loader.load_grid_stack(ds, var_name)
                if stack is not None:
                    stacks[f"{ds.dataset_id}:{var_name}"] = stack
        return stacks

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
