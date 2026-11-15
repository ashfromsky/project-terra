"""FastAPI dependencies wiring the Assessments application service."""

from typing import Annotated

from fastapi import Depends

from terra.api.dependencies import DbSessionDep, ObjectStorageDep, SettingsDep
from terra.modules.assessments.application.services import AssessmentApplicationService
from terra.modules.assessments.domain.ports import GhsDatasetClient
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.assessments.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyAssessmentRepository,
)
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository


def get_ghs_dataset_client(settings: SettingsDep) -> GhsDatasetClient:
    """Instantiate the GHS HTTP client from application settings."""
    return HttpxGhsDatasetClient(settings)


GhsDatasetClientDep = Annotated[GhsDatasetClient, Depends(get_ghs_dataset_client)]


def get_assessment_service(
    session: DbSessionDep,
    settings: SettingsDep,
    ghs_client: GhsDatasetClientDep,
    object_storage: ObjectStorageDep,
) -> AssessmentApplicationService:
    """Build a request-scoped AssessmentApplicationService."""
    return AssessmentApplicationService(
        repo=SqlAlchemyAssessmentRepository(session),
        region_repo=SqlAlchemyRegionRepository(session),
        ghs_client=ghs_client,
        artifact_root=settings.scientific_artifact_dir,
        object_storage=object_storage,
        presign_ttl_seconds=settings.s3_presign_ttl_seconds,
    )


AssessmentServiceDep = Annotated[AssessmentApplicationService, Depends(get_assessment_service)]
