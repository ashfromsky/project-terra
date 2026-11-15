"""Versioned API surface under ``/api/v1``."""

from fastapi import APIRouter

from terra.api.v1 import health, system
from terra.modules.assessments.api.router import router as assessments_router
from terra.modules.auth.api.router import router as auth_router
from terra.modules.data_sources.api.router import router as data_sources_router
from terra.modules.layers.api.router import router as layers_router
from terra.modules.regions.api.router import router as regions_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(auth_router)
api_router.include_router(regions_router)
api_router.include_router(layers_router)
api_router.include_router(data_sources_router)
api_router.include_router(assessments_router)
