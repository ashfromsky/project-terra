"""FastAPI dependency wiring for Core data sources module."""

from typing import Annotated

from fastapi import Depends

from terra.api.dependencies import DbSessionDep, SettingsDep
from terra.modules.data_sources.application.services import DataSourcesApplicationService
from terra.modules.data_sources.domain.ports import GhsServiceClient
from terra.modules.data_sources.infrastructure.ghs_service_client import HttpxGhsServiceClient
from terra.modules.data_sources.infrastructure.repositories import (
    SqlAlchemyIngestionOperationRepository,
)
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository


def get_ghs_service_client(settings: SettingsDep) -> GhsServiceClient:
    """Provide the HTTP client configured to communicate with GHS."""
    return HttpxGhsServiceClient(
        base_url=settings.ghs_base_url,
        timeout_seconds=settings.ghs_timeout_seconds,
    )


GhsServiceClientDep = Annotated[GhsServiceClient, Depends(get_ghs_service_client)]


def get_data_sources_service(
    session: DbSessionDep,
    ghs_client: GhsServiceClientDep,
) -> DataSourcesApplicationService:
    """Provide DataSourcesApplicationService wired with Core repositories and GHS HTTP client."""
    return DataSourcesApplicationService(
        ingestion_repo=SqlAlchemyIngestionOperationRepository(session),
        region_repo=SqlAlchemyRegionRepository(session),
        ghs_client=ghs_client,
    )


DataSourcesServiceDep = Annotated[
    DataSourcesApplicationService,
    Depends(get_data_sources_service),
]
