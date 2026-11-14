"""Static in-memory LayerCatalogRepository implementation."""

from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    MapLayerGroupId,
)
from terra.modules.layers.infrastructure.observation_layers import OBSERVATION_LAYERS


class StaticLayerCatalogRepository:
    """In-memory repository serving the curated TERRA layer catalog."""

    def __init__(self, layers: tuple[LayerDefinition, ...] = OBSERVATION_LAYERS) -> None:
        self._layers = layers
        self._by_id = {layer.id: layer for layer in layers}

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        return [
            layer
            for layer in self._layers
            if (group_id is None or layer.group_id == group_id)
            and (availability_status is None or layer.availability_status == availability_status)
        ]

    async def get_by_id(self, layer_id: str) -> LayerDefinition | None:
        return self._by_id.get(layer_id)
