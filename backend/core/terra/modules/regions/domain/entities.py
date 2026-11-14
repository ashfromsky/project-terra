"""Regions domain entities and value objects."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

RegionRole = Literal["primary", "regionA", "regionB"]
RegionShapeType = Literal["feature", "polygon", "rectangle"]


@dataclass(frozen=True, slots=True)
class GeometryMetrics:
    """Derived geometric properties for a validated EPSG:4326 GeoJSON shape."""

    approx_area_km2: float
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    vertex_count: int
    polygon_count: int


@dataclass(frozen=True, slots=True)
class Region:
    """User-owned geographic Area of Interest (AOI) in WGS 84 (EPSG:4326)."""

    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    role: RegionRole
    shape_type: RegionShapeType
    source_crs: Literal["EPSG:4326"]
    iso_a3: str | None
    geometry: dict[str, Any]
    metrics: GeometryMetrics
    created_at: datetime
    updated_at: datetime
