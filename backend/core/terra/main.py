"""FastAPI application factory and Granian entry point.

Startup and configuration live here; business logic belongs in the API
routers (``terra.api``) and stays independent of HTTP infrastructure.

Serve with Granian:

    uv run granian --interface asgi --host 127.0.0.1 --port 8000 terra.main:app
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from terra import __version__
from terra.api.health import router as health_router
from terra.api.v1.router import api_router
from terra.config import Settings, get_settings
from terra.infrastructure.database import DatabaseManager
from terra.infrastructure.object_storage import build_core_object_storage

logger = logging.getLogger("terra")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and dispose application-wide runtime resources."""
    settings: Settings = app.state.settings
    db = DatabaseManager(settings)
    app.state.db = db
    app.state.object_storage = build_core_object_storage(settings)

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


def _resolve_cors_policy(settings: Settings) -> tuple[list[str], bool]:
    if settings.cors_origins:
        return settings.cors_origins, settings.cors_allow_credentials
    if settings.environment == "development" and settings.frontend_auth_redirect_url:
        parsed = urlsplit(settings.frontend_auth_redirect_url)
        if parsed.scheme and parsed.netloc:
            origins = [f"{parsed.scheme}://{parsed.netloc}"]
            port_suffix = f":{parsed.port}" if parsed.port else ""
            if parsed.hostname == "localhost":
                origins.append(f"{parsed.scheme}://127.0.0.1{port_suffix}")
            elif parsed.hostname == "127.0.0.1":
                origins.append(f"{parsed.scheme}://localhost{port_suffix}")
            return origins, True
    return [], False


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application from the given (or cached) settings."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    cors_origins, allow_credentials = _resolve_cors_policy(settings)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=allow_credentials,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
        )

    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    _mount_frontend(app, settings)

    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve a built SPA from Core when FRONTEND_DIST_DIR is configured."""
    if not settings.frontend_dist_dir:
        return
    dist_dir = Path(settings.frontend_dist_dir).expanduser().resolve()
    index_path = dist_dir / "index.html"
    if not index_path.is_file():
        logger.warning("FRONTEND_DIST_DIR is set but index.html is missing: %s", dist_dir)
        return
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_fallback(full_path: str) -> FileResponse:
        # Never turn an unknown API/health path into the SPA shell.
        if full_path.startswith(("api/", "health")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (dist_dir / full_path).resolve()
        try:
            candidate.relative_to(dist_dir)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not Found") from None
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)


app = create_app()
