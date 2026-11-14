"""FastAPI application factory, exception translation, and Granian ASGI entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from geospatial_harmonization import __version__
from geospatial_harmonization.api.router import health_router, v1_router
from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import DomainError
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
from geospatial_harmonization.readers import build_default_reader_registry

logger = logging.getLogger("geospatial_harmonization")


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
    service = HarmonizationService(
        handlers=handlers,
        storage=storage,
        datasets=dataset_repo,
        readers=readers,
        max_grid_pixels=settings.max_grid_pixels,
    )

    app.state.engine = engine
    app.state.readers = readers
    app.state.handlers = handlers
    app.state.storage = storage
    app.state.dataset_repo = dataset_repo
    app.state.job_repo = job_repo
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

    app.add_exception_handler(DomainError, _handle_domain_error)
    app.include_router(health_router)
    app.include_router(health_router, prefix=cfg.api_v1_prefix)
    app.include_router(v1_router, prefix=cfg.api_v1_prefix)
    return app


app = create_app()
