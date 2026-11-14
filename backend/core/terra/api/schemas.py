"""API response schemas shared across API versions."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health probe payload."""

    status: str
    service: str
    version: str
