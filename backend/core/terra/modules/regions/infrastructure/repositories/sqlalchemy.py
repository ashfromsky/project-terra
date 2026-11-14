"""SQLAlchemy implementation of RegionRepository."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from terra.modules.regions.domain.entities import (
    GeometryMetrics,
    Region,
    RegionRole,
    RegionShapeType,
)
from terra.modules.regions.infrastructure.models import RegionModel


def _to_domain(model: RegionModel) -> Region:
    geom = model.geometry_geojson
    polygon_count = len(geom["coordinates"]) if geom.get("type") == "MultiPolygon" else 1
    bbox, centroid = model.bbox, model.centroid
    return Region(
        id=model.id,
        owner_id=model.owner_id,
        name=model.name,
        description=model.description,
        role=cast(RegionRole, model.role),
        shape_type=cast(RegionShapeType, model.shape_type),
        source_crs="EPSG:4326",
        iso_a3=model.iso_a3,
        geometry=geom,
        metrics=GeometryMetrics(
            approx_area_km2=model.approx_area_km2,
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            centroid=(centroid[0], centroid[1]),
            vertex_count=model.vertex_count,
            polygon_count=polygon_count,
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _apply_region_fields(model: RegionModel, region: Region) -> None:
    model.name, model.description, model.role = region.name, region.description, region.role
    model.shape_type, model.iso_a3 = region.shape_type, region.iso_a3
    model.geometry_geojson = region.geometry
    model.approx_area_km2 = region.metrics.approx_area_km2
    model.bbox, model.centroid = list(region.metrics.bbox), list(region.metrics.centroid)
    model.vertex_count, model.updated_at = region.metrics.vertex_count, region.updated_at


class SqlAlchemyRegionRepository:
    """Async SQLAlchemy persistence adapter for RegionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_model(self, region_id: UUID) -> RegionModel | None:
        res = await self._session.execute(select(RegionModel).where(RegionModel.id == region_id))
        return res.scalar_one_or_none()

    async def create(self, region: Region) -> Region:
        model = RegionModel(
            id=region.id,
            owner_id=region.owner_id,
            source_crs=region.source_crs,
            created_at=region.created_at,
        )
        _apply_region_fields(model, region)
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, region_id: UUID) -> Region | None:
        model = await self._get_model(region_id)
        return _to_domain(model) if model is not None else None

    async def list_by_owner(self, owner_id: UUID) -> list[Region]:
        stmt = (
            select(RegionModel)
            .where(RegionModel.owner_id == owner_id)
            .order_by(RegionModel.created_at.desc())
        )
        res = await self._session.execute(stmt)
        return [_to_domain(m) for m in res.scalars().all()]

    async def update(self, region: Region) -> Region:
        model = await self._get_model(region.id)
        if model is None:
            raise LookupError(f"Region {region.id} not found")
        _apply_region_fields(model, region)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)

    async def delete(self, region_id: UUID) -> None:
        model = await self._get_model(region_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.commit()
