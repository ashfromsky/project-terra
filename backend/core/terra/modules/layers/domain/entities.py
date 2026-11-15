"""Domain entities for the environmental map layer catalog."""

from dataclasses import dataclass
from typing import Literal

MapLayerGroupId = Literal["vegetation", "temperature", "water", "derived"]
DataAvailabilityStatus = Literal["connected", "preview", "planned", "unavailable"]
LayerRenderingType = Literal["raster", "choropleth", "vector", "point"]
TileSourceFormat = Literal["geojson", "mvt", "tilejson", "cog", "zarr", "wmts", "xyz"]
ObservationGranularity = Literal["30-minute", "daily", "8-day", "16-day", "monthly", "multi-year"]
PreviewPropertyKey = Literal["demoLstTrend", "demoNdvi", "demoEvi", "demoPrecipAnomaly"]


@dataclass(frozen=True, slots=True)
class ColorRampStop:
    """Single color stop in a continuous or diverging legend ramp."""

    value: float
    color: str
    rgb: tuple[int, int, int]
    label: str | None = None


@dataclass(frozen=True, slots=True)
class ValueRange:
    """Valid numeric range and default display stretch for a layer."""

    min: float
    max: float
    default_min: float
    default_max: float
    step: float


@dataclass(frozen=True, slots=True)
class AvailableTimeRange:
    """Nominal temporal archive bounds and native observation cadence."""

    start: str
    end: str
    cadence: ObservationGranularity


@dataclass(frozen=True, slots=True)
class LegendConfiguration:
    """Legend display labels, CSS gradient, nodata styling, and stops."""

    title: str
    unit: str
    min_label: str
    mid_label: str
    max_label: str
    gradient_css: str
    nodata_color: str
    nodata_label: str
    stops: tuple[ColorRampStop, ...]


@dataclass(frozen=True, slots=True)
class MapTileSource:
    """Tile/raster source descriptor prepared for MapLibre or TiTiler."""

    id: str
    format: TileSourceFormat
    url_template: str | None
    crs: Literal["EPSG:4326", "EPSG:3857"]
    requires_backend_authorization: bool
    is_connected: bool


@dataclass(frozen=True, slots=True)
class LayerDefinition:
    """Complete layer catalog entry aligned with frontend MapLayerDefinition."""

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
    available_time_range: AvailableTimeRange
    attribution: str
    availability_status: DataAvailabilityStatus
    rendering_type: LayerRenderingType
    supported_tile_formats: tuple[TileSourceFormat, ...]
    qa_policy: str
    limitations: str
    color_ramp: tuple[ColorRampStop, ...]
    value_range: ValueRange
    legend: LegendConfiguration
    tile_source: MapTileSource
    is_experimental: bool = False
    is_synthetic_preview: bool = False
    preview_property_key: PreviewPropertyKey | None = None
    available_dates: tuple[str, ...] = ()
    dataset_bbox: tuple[float, float, float, float] | None = None
    active_dataset_id: str | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TemporalCoverage:
    """Temporal archive window and availability summary for a layer."""

    start_date: str
    end_date: str
    cadence: ObservationGranularity
    total_expected_steps: int
    available_steps: int
    coverage_percent: float
    notes: str
    is_simulated_coverage: bool
    available_dates: tuple[str, ...] = ()
    dataset_bbox: tuple[float, float, float, float] | None = None
    active_dataset_id: str | None = None
