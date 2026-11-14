"""Pydantic schemas for the Regions API aligned with frontend AoiFeature types."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from terra.api.schemas import CamelModel
from terra.modules.regions.application.services import RegionStatistics
from terra.modules.regions.domain.entities import Region, RegionRole, RegionShapeType


def _spatial_fields(r: Region) -> dict[str, Any]:
    return {
        "source_crs": r.source_crs,
        "approx_area_km2": r.metrics.approx_area_km2,
        "bbox": list(r.metrics.bbox),
        "centroid": list(r.metrics.centroid),
    }


class _SpatialSummarySchema(CamelModel):
    source_crs: Literal["EPSG:4326"]
    approx_area_km2: float
    bbox: list[float]
    centroid: list[float]


class RegionCreateRequest(CamelModel):
    """Request payload for creating a geographic Area of Interest."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    role: RegionRole = "primary"
    shape_type: RegionShapeType = "polygon"
    iso_a3: str | None = Field(default=None, min_length=3, max_length=3)
    geometry: dict[str, Any]


class RegionUpdateMetadataRequest(CamelModel):
    """Partial metadata update payload for an existing region."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    role: RegionRole | None = None
    shape_type: RegionShapeType | None = None
    iso_a3: str | None = Field(default=None, min_length=3, max_length=3)


class RegionUpdateGeometryRequest(CamelModel):
    """Replacement GeoJSON geometry payload for an existing region."""

    geometry: dict[str, Any]
    shape_type: RegionShapeType | None = None


class RegionResponse(_SpatialSummarySchema):
    """Full region representation with derived WGS 84 metrics and GeoJSON."""

    id: UUID
    name: str
    description: str | None
    role: RegionRole
    shape_type: RegionShapeType
    iso_a3: str | None
    vertex_count: int
    polygon_count: int
    geometry: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, r: Region) -> "RegionResponse":
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            role=r.role,
            shape_type=r.shape_type,
            iso_a3=r.iso_a3,
            vertex_count=r.metrics.vertex_count,
            polygon_count=r.metrics.polygon_count,
            geometry=r.geometry,
            created_at=r.created_at,
            updated_at=r.updated_at,
            **_spatial_fields(r),
        )


class AoiPropertiesResponse(_SpatialSummarySchema):
    """GeoJSON Feature properties matching frontend AoiProperties."""

    id: UUID
    name: str
    role: RegionRole
    shape_type: RegionShapeType
    created_at: datetime
    iso_a3: str | None = None


class RegionGeometryResponse(CamelModel):
    """GeoJSON Feature representation matching frontend AoiFeature."""

    type: Literal["Feature"] = "Feature"
    id: UUID
    properties: AoiPropertiesResponse
    geometry: dict[str, Any]

    @classmethod
    def from_domain(cls, r: Region) -> "RegionGeometryResponse":
        props = AoiPropertiesResponse(
            id=r.id,
            name=r.name,
            role=r.role,
            shape_type=r.shape_type,
            created_at=r.created_at,
            iso_a3=r.iso_a3,
            **_spatial_fields(r),
        )
        return cls(id=r.id, properties=props, geometry=r.geometry)


class RegionStatisticsResponse(_SpatialSummarySchema):
    """Available geometric and environmental statistics for a region."""

    region_id: UUID
    region_name: str
    vertex_count: int
    polygon_count: int
    observation_status: str
    message: str
    available_metrics: list[str]

    @classmethod
    def from_domain(cls, stats: RegionStatistics) -> "RegionStatisticsResponse":
        r = stats.region
        return cls(
            region_id=r.id,
            region_name=r.name,
            vertex_count=r.metrics.vertex_count,
            polygon_count=r.metrics.polygon_count,
            observation_status=stats.observation_status,
            message=stats.message,
            available_metrics=["approxAreaKm2", "bbox", "centroid", "vertexCount", "polygonCount"],
            **_spatial_fields(r),
        )
