"""Pydantic schemas for Layers REST API responses in camelCase."""

from typing import Literal

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from terra.api.schemas import CamelModel
from terra.modules.layers.domain.entities import (
    DataAvailabilityStatus,
    LayerDefinition,
    LayerRenderingType,
    LegendConfiguration,
    MapLayerGroupId,
    ObservationGranularity,
    PreviewPropertyKey,
    TemporalCoverage,
    TileSourceFormat,
)


class _LayerSchema(CamelModel):
    """Base schema supporting direct validation from frozen domain dataclasses."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ColorRampStopResponse(_LayerSchema):
    """Single stop in a layer color ramp."""

    value: float
    color: str
    rgb: tuple[int, int, int]
    label: str | None = None


class ValueRangeResponse(_LayerSchema):
    """Valid range and default stretch bounds."""

    min: float
    max: float
    default_min: float
    default_max: float
    step: float


class AvailableTimeRangeResponse(_LayerSchema):
    """Nominal temporal window and cadence."""

    start: str
    end: str
    cadence: ObservationGranularity


class LegendConfigurationResponse(_LayerSchema):
    """Legend display properties and ramp stops."""

    title: str
    unit: str
    min_label: str
    mid_label: str
    max_label: str
    gradient_css: str
    nodata_color: str
    nodata_label: str
    stops: list[ColorRampStopResponse]


class MapTileSourceResponse(_LayerSchema):
    """Tile or raster source descriptor."""

    id: str
    format: TileSourceFormat
    url_template: str | None
    crs: Literal["EPSG:4326", "EPSG:3857"]
    requires_backend_authorization: bool
    is_connected: bool


class LayerMetadataResponse(_LayerSchema):
    """Layer scientific provenance, units, QA policy, and limitations."""

    id: str
    name: str
    short_name: str
    group_id: MapLayerGroupId
    description: str
    data_source: str
    product_id: str
    product_version: str
    variable: str
    unit: str
    native_spatial_resolution: str
    temporal_resolution: str
    available_time_range: AvailableTimeRangeResponse
    attribution: str
    availability_status: DataAvailabilityStatus
    rendering_type: LayerRenderingType
    supported_tile_formats: list[TileSourceFormat]
    qa_policy: str
    limitations: str
    is_experimental: bool
    is_synthetic_preview: bool
    preview_property_key: PreviewPropertyKey | None = None


class LayerDefinitionResponse(LayerMetadataResponse):
    """Complete layer catalog entry aligned with frontend MapLayerDefinition."""

    color_ramp: list[ColorRampStopResponse]
    value_range: ValueRangeResponse
    legend: LegendConfigurationResponse
    tile_source: MapTileSourceResponse


class LayerLegendResponse(LegendConfigurationResponse):
    """Layer legend payload paired with layer identifier and display value range."""

    layer_id: str
    value_range: ValueRangeResponse

    @classmethod
    def from_domain(
        cls, layer: LayerDefinition, legend: LegendConfiguration
    ) -> "LayerLegendResponse":
        return cls(
            layer_id=layer.id,
            value_range=ValueRangeResponse.model_validate(layer.value_range),
            title=legend.title,
            unit=legend.unit,
            min_label=legend.min_label,
            mid_label=legend.mid_label,
            max_label=legend.max_label,
            gradient_css=legend.gradient_css,
            nodata_color=legend.nodata_color,
            nodata_label=legend.nodata_label,
            stops=[ColorRampStopResponse.model_validate(stop) for stop in legend.stops],
        )


class TemporalCoverageResponse(_LayerSchema):
    """Temporal archive coverage summary for a layer."""

    layer_id: str
    start_date: str
    end_date: str
    cadence: ObservationGranularity
    total_expected_steps: int
    available_steps: int
    coverage_percent: float
    notes: str
    is_simulated_coverage: bool

    @classmethod
    def from_domain(cls, layer_id: str, coverage: TemporalCoverage) -> "TemporalCoverageResponse":
        return cls(
            layer_id=layer_id,
            start_date=coverage.start_date,
            end_date=coverage.end_date,
            cadence=coverage.cadence,
            total_expected_steps=coverage.total_expected_steps,
            available_steps=coverage.available_steps,
            coverage_percent=coverage.coverage_percent,
            notes=coverage.notes,
            is_simulated_coverage=coverage.is_simulated_coverage,
        )
