"""Unit and integration tests for region geometry validation and persistence."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from terra.config import Settings
from terra.infrastructure.database import DatabaseManager
from terra.modules.auth.domain.entities import GitHubProfile
from terra.modules.auth.infrastructure.repositories.sqlalchemy import SqlAlchemyUserRepository
from terra.modules.regions.domain.entities import Region
from terra.modules.regions.domain.exceptions import InvalidGeometryError
from terra.modules.regions.domain.geometry import validate_and_measure_geometry
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository

_BOX = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


def test_geometry_validation_computes_area_bbox_and_centroid() -> None:
    geom, metrics = validate_and_measure_geometry(_BOX)
    assert geom["type"] == "Polygon"
    assert metrics.bbox == (0.0, 0.0, 1.0, 1.0)
    assert metrics.centroid == (0.5, 0.5)
    assert metrics.vertex_count == 4
    assert 12_000 < metrics.approx_area_km2 < 12_600


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "Point", "coordinates": [0.0, 0.0]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Polygon", "coordinates": [[[200, 0], [1, 0], [1, 1], [0, 1], [200, 0]]]},
    ],
)
def test_geometry_validation_rejects_invalid_shapes(bad: dict) -> None:
    with pytest.raises(InvalidGeometryError):
        validate_and_measure_geometry(bad)


def test_sqlalchemy_region_repository_crud() -> None:
    async def scenario() -> None:
        db = DatabaseManager(Settings(environment="test"))
        await db.create_schema()
        try:
            async with db.session() as session:
                user = await SqlAlchemyUserRepository(session).upsert_by_github_id(
                    GitHubProfile(github_id=101, github_login="tester")
                )
                repo = SqlAlchemyRegionRepository(session)
                geom, metrics = validate_and_measure_geometry(_BOX)
                now = datetime.now(UTC)
                fields = {
                    "id": uuid4(),
                    "owner_id": user.id,
                    "name": "Box",
                    "description": None,
                    "role": "primary",
                    "shape_type": "rectangle",
                    "source_crs": "EPSG:4326",
                    "iso_a3": None,
                    "geometry": geom,
                    "metrics": metrics,
                    "created_at": now,
                    "updated_at": now,
                }
                region = Region(**fields)
                await repo.create(region)
                assert len(await repo.list_by_owner(user.id)) == 1
                fetched = await repo.get_by_id(region.id)
                assert fetched is not None and fetched.metrics.vertex_count == 4
                await repo.delete(region.id)
                assert await repo.get_by_id(region.id) is None
        finally:
            await db.dispose()

    asyncio.run(scenario())
