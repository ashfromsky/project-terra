"""Versioned API surface under ``/api/v1``."""

from fastapi import APIRouter

from terra.api.v1 import health, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
