"""Static in-memory LayerCatalogRepository implementation."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    MapLayerGroupId,
)
from terra.modules.layers.infrastructure.derived_layers import DERIVED_LAYERS
from terra.modules.layers.infrastructure.observation_layers import OBSERVATION_LAYERS
from terra.modules.layers.infrastructure.resilience_layers import RESILIENCE_LAYERS

ALL_LAYERS: tuple[LayerDefinition, ...] = OBSERVATION_LAYERS + DERIVED_LAYERS + RESILIENCE_LAYERS


def _today_utc_iso() -> str:
    return datetime.now(UTC).date().isoformat()


class StaticLayerCatalogRepository:
    """In-memory repository serving the curated TERRA layer catalog."""

    def __init__(
        self,
        layers: tuple[LayerDefinition, ...] = ALL_LAYERS,
        *,
        date_provider: Callable[[], str] = _today_utc_iso,
    ) -> None:
        self._layers = layers
        self._by_id = {layer.id: layer for layer in layers}
        self._date_provider = date_provider

    def _with_current_archive_end(self, layer: LayerDefinition) -> LayerDefinition:
        today_iso = self._date_provider()
        if layer.available_time_range.end >= today_iso:
            return layer
        return replace(
            layer,
            available_time_range=replace(layer.available_time_range, end=today_iso),
        )

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        return [
            self._with_current_archive_end(layer)
            for layer in self._layers
            if (group_id is None or layer.group_id == group_id)
            and (availability_status is None or layer.availability_status == availability_status)
        ]

    async def get_by_id(self, layer_id: str) -> LayerDefinition | None:
        layer = self._by_id.get(layer_id)
        if layer is None:
            return None
        return self._with_current_archive_end(layer)
