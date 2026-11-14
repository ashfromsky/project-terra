"""Application service unit tests for Regions using a fake repository."""

import asyncio
from uuid import UUID, uuid4

import pytest

from terra.modules.regions.application.services import RegionService
from terra.modules.regions.domain.entities import Region
from terra.modules.regions.domain.exceptions import (
    InvalidGeometryError,
    RegionAccessDeniedError,
    RegionNotFoundError,
)

_BOX_1 = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
_BOX_2 = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


class FakeRegionRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, Region] = {}

    async def create(self, region: Region) -> Region:
        self._items[region.id] = region
        return region

    async def get_by_id(self, region_id: UUID) -> Region | None:
        return self._items.get(region_id)

    async def list_by_owner(self, owner_id: UUID) -> list[Region]:
        return [r for r in self._items.values() if r.owner_id == owner_id]

    async def update(self, region: Region) -> Region:
        self._items[region.id] = region
        return region

    async def delete(self, region_id: UUID) -> None:
        self._items.pop(region_id, None)


def test_region_service_lifecycle_and_ownership_rules() -> None:
    async def scenario() -> None:
        service = RegionService(FakeRegionRepository())
        owner_a, owner_b = uuid4(), uuid4()

        created = await service.create_region(
            owner_id=owner_a,
            name="  Amazon AOI  ",
            geometry=_BOX_1,
            iso_a3="bra",
        )
        assert created.name == "Amazon AOI"
        assert created.iso_a3 == "BRA"

        updated = await service.update_metadata(
            created.id, owner_a, name="Updated AOI", role="regionA", description=None
        )
        assert updated.name == "Updated AOI"
        assert updated.role == "regionA"

        regeom = await service.update_geometry(created.id, owner_a, geometry=_BOX_2)
        assert regeom.metrics.approx_area_km2 > created.metrics.approx_area_km2 * 3

        stats = await service.get_statistics(created.id, owner_a)
        assert stats.observation_status == "unavailable"

        with pytest.raises(RegionAccessDeniedError):
            await service.get_region(created.id, owner_b)

        with pytest.raises(RegionAccessDeniedError):
            await service.delete_region(created.id, owner_b)

        await service.delete_region(created.id, owner_a)
        with pytest.raises(RegionNotFoundError):
            await service.get_region(created.id, owner_a)

    asyncio.run(scenario())


def test_region_service_rejects_invalid_geometry_on_update() -> None:
    async def scenario() -> None:
        service = RegionService(FakeRegionRepository())
        owner = uuid4()
        created = await service.create_region(owner_id=owner, name="AOI", geometry=_BOX_1)
        with pytest.raises(InvalidGeometryError):
            await service.update_geometry(
                created.id,
                owner,
                geometry={"type": "Point", "coordinates": [0, 0]},
            )

    asyncio.run(scenario())
