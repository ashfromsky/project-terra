"""Integrity tests for the observation layers and StaticLayerCatalogRepository."""

import asyncio

from terra.modules.layers.infrastructure.static_repository import StaticLayerCatalogRepository


def test_observation_catalog_contains_expected_layers() -> None:
    async def scenario() -> None:
        repo = StaticLayerCatalogRepository()
        layers = await repo.list_layers()
        assert len(layers) == 6
        assert {layer.group_id for layer in layers} == {"vegetation", "temperature", "water"}
        assert await repo.get_by_id("ndvi-mod13q1") is not None
        assert await repo.get_by_id("soil-moisture-smap") is not None
        assert len(await repo.list_layers(group_id="water")) == 2

    asyncio.run(scenario())
