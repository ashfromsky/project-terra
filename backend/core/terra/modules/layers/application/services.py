"""Application service for layer catalog, metadata, legend, and coverage."""

from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    LegendConfiguration,
    MapLayerGroupId,
    ObservationGranularity,
    TemporalCoverage,
)
from terra.modules.layers.domain.exceptions import LayerNotFoundError
from terra.modules.layers.domain.repositories import LayerCatalogRepository

_STEPS_PER_YEAR: dict[ObservationGranularity, int] = {
    "16-day": 23,
    "8-day": 46,
    "daily": 365,
    "30-minute": 17_520,
    "monthly": 12,
    "multi-year": 12,
}


class LayerCatalogService:
    """Coordinates layer catalog discovery and temporal coverage estimation."""

    def __init__(self, repo: LayerCatalogRepository) -> None:
        self._repo = repo

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        """Return catalog layers matching optional filters."""
        return await self._repo.list_layers(
            group_id=group_id,
            availability_status=availability_status,
        )

    async def get_layer(self, layer_id: str) -> LayerDefinition:
        """Return a single layer definition or raise LayerNotFoundError."""
        layer = await self._repo.get_by_id(layer_id)
        if layer is None:
            raise LayerNotFoundError(f"Layer '{layer_id}' not found")
        return layer

    async def get_legend(self, layer_id: str) -> tuple[LayerDefinition, LegendConfiguration]:
        """Return the layer and its legend configuration."""
        layer = await self.get_layer(layer_id)
        return layer, layer.legend

    async def get_coverage(self, layer_id: str) -> TemporalCoverage:
        """Return nominal archive temporal coverage until live ingestion is connected."""
        layer = await self.get_layer(layer_id)
        tr = layer.available_time_range
        start_year = int(tr.start[:4])
        end_year = int(tr.end[:4])
        years = max(1, end_year - start_year + 1)
        total_expected_steps = years * _STEPS_PER_YEAR[tr.cadence]
        return TemporalCoverage(
            start_date=tr.start,
            end_date=tr.end,
            cadence=tr.cadence,
            total_expected_steps=total_expected_steps,
            available_steps=0,
            coverage_percent=0.0,
            notes=(
                "Nominal archive bounds shown for planning. Live granule discovery and "
                "valid-observation counts require backend Earthdata / Worker ingestion."
            ),
            is_simulated_coverage=True,
        )
