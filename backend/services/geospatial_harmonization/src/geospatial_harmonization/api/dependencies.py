"""FastAPI dependency wiring for GHS application services and infrastructure ports."""

from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.domain.ports import (
    DatasetRepository,
    JobRepository,
    StorageLedgerRepository,
    StoragePort,
)
from geospatial_harmonization.handlers.registry import HandlerRegistry
from geospatial_harmonization.readers import ReaderRegistry
from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
from geospatial_harmonization.storage.monitoring import StorageMonitoringService
from geospatial_harmonization.storage.quota import StorageQuotaManager


def get_runtime_settings(request: Request) -> Settings:
    """Return active service Settings stored on FastAPI application state."""
    return cast("Settings", request.app.state.settings)


def get_db_engine(request: Request) -> AsyncEngine:
    """Return the AsyncEngine managed by application lifespan."""
    return cast("AsyncEngine", request.app.state.engine)


def get_storage(request: Request) -> StoragePort:
    """Return configured StoragePort instance."""
    return cast("StoragePort", request.app.state.storage)


def get_handler_registry(request: Request) -> HandlerRegistry:
    """Return configured provider HandlerRegistry."""
    return cast("HandlerRegistry", request.app.state.handlers)


def get_reader_registry(request: Request) -> ReaderRegistry:
    """Return configured format ReaderRegistry."""
    return cast("ReaderRegistry", request.app.state.readers)


def get_dataset_repo(request: Request) -> DatasetRepository:
    """Return DatasetRepository bound to the application session factory."""
    return cast("DatasetRepository", request.app.state.dataset_repo)


def get_job_repo(request: Request) -> JobRepository:
    """Return JobRepository bound to the application session factory."""
    return cast("JobRepository", request.app.state.job_repo)


def get_harmonization_service(request: Request) -> HarmonizationService:
    """Return HarmonizationService use-case orchestrator."""
    return cast("HarmonizationService", request.app.state.harmonization_service)


def get_storage_ledger(request: Request) -> StorageLedgerRepository:
    """Return StorageLedgerRepository bound to application sessions."""
    return cast("StorageLedgerRepository", request.app.state.ledger)


def get_storage_quota(request: Request) -> StorageQuotaManager:
    """Return StorageQuotaManager enforcing budget reservations."""
    return cast("StorageQuotaManager", request.app.state.quota)


def get_storage_lifecycle(request: Request) -> StorageLifecycleManager:
    """Return StorageLifecycleManager coordinating mark-and-sweep cleanup."""
    return cast("StorageLifecycleManager", request.app.state.lifecycle)


def get_storage_monitoring(request: Request) -> StorageMonitoringService:
    """Return StorageMonitoringService providing usage and policy reports."""
    return cast("StorageMonitoringService", request.app.state.monitoring)


SettingsDep = Annotated[Settings, Depends(get_runtime_settings)]
EngineDep = Annotated[AsyncEngine, Depends(get_db_engine)]
StorageDep = Annotated[StoragePort, Depends(get_storage)]
HandlersDep = Annotated[HandlerRegistry, Depends(get_handler_registry)]
ReadersDep = Annotated[ReaderRegistry, Depends(get_reader_registry)]
DatasetRepoDep = Annotated[DatasetRepository, Depends(get_dataset_repo)]
JobRepoDep = Annotated[JobRepository, Depends(get_job_repo)]
HarmonizationServiceDep = Annotated[HarmonizationService, Depends(get_harmonization_service)]
StorageLedgerDep = Annotated[StorageLedgerRepository, Depends(get_storage_ledger)]
StorageQuotaDep = Annotated[StorageQuotaManager, Depends(get_storage_quota)]
StorageLifecycleDep = Annotated[StorageLifecycleManager, Depends(get_storage_lifecycle)]
StorageMonitoringDep = Annotated[StorageMonitoringService, Depends(get_storage_monitoring)]
