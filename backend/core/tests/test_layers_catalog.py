"""Integrity tests for the layer catalog and StaticLayerCatalogRepository."""

import asyncio

from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


def test_full_catalog_contains_all_sixteen_layers() -> None:
    async def scenario() -> None:
        repo = StaticLayerCatalogRepository()
        layers = await repo.list_layers()
        assert len(layers) == 16
        assert {layer.group_id for layer in layers} == {
            "vegetation",
            "temperature",
            "water",
            "derived",
        }
        assert len(await repo.list_layers(group_id="water")) == 2
        assert len(await repo.list_layers(group_id="derived")) == 10
        assert await repo.get_by_id("ndvi-mod13q1") is not None
        assert await repo.get_by_id("soil-moisture-smap") is not None
        assert await repo.get_by_id("mann-kendall-significance") is not None
        assert await repo.get_by_id("resistance") is not None
        tri = await repo.get_by_id("experimental-tri")
        assert tri is not None
        assert tri.is_experimental is True

    asyncio.run(scenario())


def test_catalog_repository_advances_archive_end_dynamically() -> None:
    async def scenario() -> None:
        current_day = "2026-11-18"
        repo = StaticLayerCatalogRepository(date_provider=lambda: current_day)

        layer = await repo.get_by_id("ndvi-mod13q1")
        assert layer is not None
        assert layer.available_time_range.end == "2026-11-18"

        current_day = "2026-11-19"
        layers = await repo.list_layers(group_id="vegetation")
        assert all(item.available_time_range.end == "2026-11-19" for item in layers)

    asyncio.run(scenario())
