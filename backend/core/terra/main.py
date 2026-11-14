"""FastAPI application factory and Granian entry point.

Startup and configuration live here; business logic belongs in the API
routers (``terra.api``) and stays independent of HTTP infrastructure.

Serve with Granian:

    uv run granian --interface asgi --host 127.0.0.1 --port 8000 terra.main:app
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from terra import __version__
from terra.api.health import router as health_router
from terra.api.v1.router import api_router
from terra.config import Settings, get_settings
from terra.infrastructure.database import DatabaseManager

logger = logging.getLogger("terra")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and dispose application-wide runtime resources."""
    settings: Settings = app.state.settings
    db = DatabaseManager(settings)
    app.state.db = db

    if settings.database_auto_create_tables and settings.environment != "production":
        await db.create_schema()

    logger.info(
        "Starting %s (environment=%s, version=%s)",
        settings.app_name,
        settings.environment,
        __version__,
    )
    try:
        yield
    finally:
        await db.dispose()
        logger.info("Shutting down %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application from the given (or cached) settings."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=settings.cors_allow_credentials,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
        )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
