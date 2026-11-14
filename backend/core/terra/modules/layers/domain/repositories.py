"""Repository contract for environmental map layer catalog queries."""

from typing import Protocol

from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    MapLayerGroupId,
)


class LayerCatalogRepository(Protocol):
    """Read-only port for discovering environmental map layers."""

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        """Return layers optionally filtered by group or availability status."""
        ...

    async def get_by_id(self, layer_id: str) -> LayerDefinition | None:
        """Return a layer definition by ID or None if not found."""
        ...
