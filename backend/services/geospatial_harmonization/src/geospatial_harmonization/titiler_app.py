"""Dedicated TiTiler Service application for Project TERRA.

Exposes Cloud Optimized GeoTIFF inspection, metadata, TileJSON, and dynamic
raster tile streaming. Can be deployed as a dedicated service or mounted within GHS.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.titiler.router import create_titiler_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting Project TERRA TiTiler Service")
    yield
    logger.info("Stopped Project TERRA TiTiler Service")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    app = FastAPI(
        title="TERRA TiTiler Raster Service",
        description="Dynamic Cloud Optimized GeoTIFF raster tile streaming and visualization.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "titiler", "version": "0.1.0"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        return {"status": "ready", "service": "titiler"}

    cog_router = create_titiler_router(cfg)
    app.include_router(cog_router, prefix="/cog")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(
        "geospatial_harmonization.titiler_app:app",
        host="127.0.0.1",
        port=8082,
        reload=False,
    )
