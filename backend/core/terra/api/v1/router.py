"""Versioned API surface under ``/api/v1``."""

from fastapi import APIRouter

from terra.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
