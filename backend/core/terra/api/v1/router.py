"""Versioned API surface under ``/api/v1``."""

from fastapi import APIRouter

from terra.api.v1 import health, system
from terra.modules.auth.api.router import router as auth_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(auth_router)
