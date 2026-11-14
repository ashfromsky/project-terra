"""Application services for managing user-owned geographic regions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from terra.modules.regions.domain.entities import Region, RegionRole, RegionShapeType
from terra.modules.regions.domain.exceptions import (
    RegionAccessDeniedError,
    RegionDomainError,
    RegionNotFoundError,
)
from terra.modules.regions.domain.geometry import validate_and_measure_geometry
from terra.modules.regions.domain.repositories import RegionRepository


class _Unset(Enum):
    TOKEN = auto()


UNSET = _Unset.TOKEN


@dataclass(frozen=True, slots=True)
class RegionStatistics:
    """Geometric and observational availability summary for a Region."""

    region: Region
    observation_status: str
    message: str


def _normalize_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise RegionDomainError("Region name must not be empty")
    return cleaned


class RegionService:
    """Coordinates region validation, ownership enforcement, and persistence."""

    def __init__(self, repo: RegionRepository) -> None:
        self._repo = repo

    async def _require_owned(self, region_id: UUID, owner_id: UUID) -> Region:
        region = await self._repo.get_by_id(region_id)
        if region is None:
            raise RegionNotFoundError(f"Region {region_id} not found")
        if region.owner_id != owner_id:
            raise RegionAccessDeniedError("You do not have access to this region")
        return region

    async def create_region(
        self,
        *,
        owner_id: UUID,
        name: str,
        geometry: dict[str, Any],
        role: RegionRole = "primary",
        shape_type: RegionShapeType = "polygon",
        description: str | None = None,
        iso_a3: str | None = None,
    ) -> Region:
        """Validate EPSG:4326 geometry, compute metrics, and persist a new region."""
        normalized_geom, metrics = validate_and_measure_geometry(geometry)
        now = datetime.now(UTC)
        region = Region(
            id=uuid4(),
            owner_id=owner_id,
            name=_normalize_name(name),
            description=description,
            role=role,
            shape_type=shape_type,
            source_crs="EPSG:4326",
            iso_a3=iso_a3.upper() if iso_a3 else None,
            geometry=normalized_geom,
            metrics=metrics,
            created_at=now,
            updated_at=now,
        )
        return await self._repo.create(region)

    async def list_regions(self, owner_id: UUID) -> list[Region]:
        """List all regions belonging to the authenticated user."""
        return await self._repo.list_by_owner(owner_id)

    async def get_region(self, region_id: UUID, owner_id: UUID) -> Region:
        """Return a single region owned by the authenticated user."""
        return await self._require_owned(region_id, owner_id)

    async def update_metadata(
        self,
        region_id: UUID,
        owner_id: UUID,
        *,
        name: str | _Unset = UNSET,
        description: str | _Unset | None = UNSET,
        role: RegionRole | _Unset = UNSET,
        shape_type: RegionShapeType | _Unset = UNSET,
        iso_a3: str | _Unset | None = UNSET,
    ) -> Region:
        """Update mutable region metadata without altering geometry."""
        current = await self._require_owned(region_id, owner_id)
        next_name = current.name if isinstance(name, _Unset) else _normalize_name(name)
        next_desc = current.description if isinstance(description, _Unset) else description
        next_role = current.role if isinstance(role, _Unset) else role
        next_shape = current.shape_type if isinstance(shape_type, _Unset) else shape_type
        if isinstance(iso_a3, _Unset):
            next_iso = current.iso_a3
        else:
            next_iso = iso_a3.upper() if iso_a3 else None

        updated = Region(
            id=current.id,
            owner_id=current.owner_id,
            name=next_name,
            description=next_desc,
            role=next_role,
            shape_type=next_shape,
            source_crs=current.source_crs,
            iso_a3=next_iso,
            geometry=current.geometry,
            metrics=current.metrics,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        return await self._repo.update(updated)

    async def update_geometry(
        self,
        region_id: UUID,
        owner_id: UUID,
        *,
        geometry: dict[str, Any],
        shape_type: RegionShapeType | None = None,
    ) -> Region:
        """Validate replacement geometry, recompute metrics, and persist."""
        current = await self._require_owned(region_id, owner_id)
        normalized_geom, metrics = validate_and_measure_geometry(geometry)
        updated = Region(
            id=current.id,
            owner_id=current.owner_id,
            name=current.name,
            description=current.description,
            role=current.role,
            shape_type=shape_type or current.shape_type,
            source_crs="EPSG:4326",
            iso_a3=current.iso_a3,
            geometry=normalized_geom,
            metrics=metrics,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        return await self._repo.update(updated)

    async def delete_region(self, region_id: UUID, owner_id: UUID) -> None:
        """Verify ownership and delete the region."""
        await self._require_owned(region_id, owner_id)
        await self._repo.delete(region_id)

    async def get_statistics(self, region_id: UUID, owner_id: UUID) -> RegionStatistics:
        """Return geometric metrics and honest environmental statistics availability."""
        region = await self._require_owned(region_id, owner_id)
        return RegionStatistics(
            region=region,
            observation_status="unavailable",
            message=(
                "Geometric metrics are computed from WGS 84 (EPSG:4326) boundaries. "
                "Zonal environmental statistics await backend dataset ingestion."
            ),
        )
