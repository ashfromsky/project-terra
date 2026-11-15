"""FastAPI application factory, exception translation, and Granian ASGI entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from geospatial_harmonization import __version__
from geospatial_harmonization.api.router import health_router, v1_router
from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import (
    DomainError,
    ObjectTooLargeError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderDisabledError,
    ProviderIngestionError,
    ProviderResponseError,
    StorageBudgetExceededError,
    StorageImmutabilityError,
    TransientTransferError,
)
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyJobRepository,
)
from geospatial_harmonization.infrastructure.storage import build_storage_port
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository
from geospatial_harmonization.readers import build_default_reader_registry
from geospatial_harmonization.storage import (
    ContentDeduplicationService,
    DataCompressionManager,
    StorageLifecycleManager,
    StorageMonitoringService,
    StorageQuotaManager,
    StorageZoneManager,
)

logger = logging.getLogger("geospatial_harmonization")


async def _handle_budget_exceeded(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StorageBudgetExceededError)
    return JSONResponse(
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        content={
            "detail": str(exc),
            "error_type": type(exc).__name__,
            "code": exc.code,
            "requested_bytes": exc.requested_bytes,
            "available_bytes": exc.available_bytes,
            "budget_bytes": exc.budget_bytes,
            "reserved_bytes": exc.reserved_bytes,
            "zone": exc.zone,
        },
    )


async def _handle_object_too_large(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ObjectTooLargeError)
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={
            "detail": str(exc),
            "error_type": type(exc).__name__,
            "code": exc.code,
            "requested_bytes": exc.requested_bytes,
            "limit_bytes": exc.limit_bytes,
            "scope": exc.scope,
        },
    )


async def _handle_storage_immutability(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "error_type": type(exc).__name__},
    )


async def _handle_provider_ingestion_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProviderIngestionError)
    if isinstance(exc, (ProviderDisabledError, TransientTransferError)):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(
        exc,
        (ProviderAuthenticationError, ProviderAuthorizationError, ProviderResponseError),
    ):
        http_status = status.HTTP_502_BAD_GATEWAY
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return JSONResponse(
        status_code=http_status,
        content={
            "detail": str(exc),
            "error_type": type(exc).__name__,
            "error_category": exc.error_category,
            "retryable": exc.retryable,
        },
    )


async def _handle_domain_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc), "error_type": type(exc).__name__},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and cleanly tear down database, storage, and service dependencies."""
    settings: Settings = app.state.settings
    engine = build_async_engine(settings.database_url, echo=settings.database_echo)
    if settings.environment != "production" and settings.database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)

    sessions = build_session_factory(engine)
    readers = build_default_reader_registry()
    handlers = build_default_handler_registry(settings=settings, reader_registry=readers)
    storage = build_storage_port(settings)
    dataset_repo = SqlAlchemyDatasetRepository(sessions)
    job_repo = SqlAlchemyJobRepository(sessions)
    ledger = SqlAlchemyStorageLedgerRepository(sessions)
    await ledger.ensure_ledger_initialized(datetime.now(UTC))
    zones = StorageZoneManager(settings)
    quota = StorageQuotaManager(ledger, storage, settings)
    dedup = ContentDeduplicationService(storage, ledger, zones, settings)
    lifecycle = StorageLifecycleManager(storage, ledger, zones, settings)
    monitoring = StorageMonitoringService(ledger, quota, zones, settings)
    compression = DataCompressionManager(settings)
    service = HarmonizationService(
        handlers=handlers,
        storage=storage,
        datasets=dataset_repo,
        readers=readers,
        max_grid_pixels=settings.max_grid_pixels,
        settings=settings,
        ledger=ledger,
        zones=zones,
        quota=quota,
        dedup=dedup,
        lifecycle=lifecycle,
        compression=compression,
    )

    app.state.engine = engine
    app.state.readers = readers
    app.state.handlers = handlers
    app.state.storage = storage
    app.state.dataset_repo = dataset_repo
    app.state.job_repo = job_repo
    app.state.ledger = ledger
    app.state.zones = zones
    app.state.quota = quota
    app.state.dedup = dedup
    app.state.lifecycle = lifecycle
    app.state.monitoring = monitoring
    app.state.compression = compression
    app.state.harmonization_service = service
    logger.info("Started %s (%s)", settings.app_name, __version__)
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Stopped %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the ASGI FastAPI application from configuration."""
    cfg = settings or get_settings()
    app = FastAPI(title=cfg.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = cfg

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=cfg.cors_allow_credentials,
            allow_methods=cfg.cors_allow_methods,
            allow_headers=cfg.cors_allow_headers,
        )

    app.add_exception_handler(StorageBudgetExceededError, _handle_budget_exceeded)
    app.add_exception_handler(ObjectTooLargeError, _handle_object_too_large)
    app.add_exception_handler(StorageImmutabilityError, _handle_storage_immutability)
    app.add_exception_handler(ProviderIngestionError, _handle_provider_ingestion_error)
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.include_router(health_router)
    app.include_router(health_router, prefix=cfg.api_v1_prefix)
    app.include_router(v1_router, prefix=cfg.api_v1_prefix)
    return app


app = create_app()
