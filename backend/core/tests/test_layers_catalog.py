"""Integrity tests for the layer catalog and StaticLayerCatalogRepository."""

import asyncio

from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


def test_catalog_contains_observation_and_derived_trend_layers() -> None:
    async def scenario() -> None:
        repo = StaticLayerCatalogRepository()
        layers = await repo.list_layers()
        assert len(layers) == 11
        assert {layer.group_id for layer in layers} == {
            "vegetation",
            "temperature",
            "water",
            "derived",
        }
        assert len(await repo.list_layers(group_id="water")) == 2
        assert len(await repo.list_layers(group_id="derived")) == 5
        assert await repo.get_by_id("ndvi-mod13q1") is not None
        assert await repo.get_by_id("soil-moisture-smap") is not None
        assert await repo.get_by_id("mann-kendall-significance") is not None
        assert await repo.get_by_id("sens-slope") is not None

    asyncio.run(scenario())
