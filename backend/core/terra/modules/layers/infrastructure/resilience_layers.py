"""Resilience and experimental TRI layer definitions aligned with resilience-layers.ts."""

from terra.modules.layers.domain.entities import (
    AvailableTimeRange,
    DataAvailabilityStatus,
    LayerDefinition,
    LegendConfiguration,
    MapTileSource,
    TileSourceFormat,
    ValueRange,
)
from terra.modules.layers.infrastructure.color_ramps import RESILIENCE_RAMP

_RESILIENCE_GRADIENT = "linear-gradient(90deg, #c77f6d 0%, #ead6bc 50%, #159b91 100%)"
_REVERSED_RESILIENCE_GRADIENT = "linear-gradient(90deg, #159b91 0%, #ead6bc 50%, #c77f6d 100%)"
_RESILIENCE_VALUE_RANGE = ValueRange(0.0, 100.0, 0.0, 100.0, 5.0)


def _build_resilience_layer(
    *,
    layer_id: str,
    name: str,
    short_name: str,
    description: str,
    product_id: str,
    variable: str,
    legend_title: str,
    min_label: str,
    max_label: str,
    nodata_label: str,
    tile_source_id: str,
    qa_policy: str,
    limitations: str,
    native_spatial_resolution: str = "AOI / Source grid",
    product_version: str = "v0.1",
    data_source: str = "TERRA Scientific Core · Resilience assessment",
    legend_unit: str = "index (0-100)",
    gradient_css: str = _RESILIENCE_GRADIENT,
    attribution: str = "TERRA Scientific Core · Pending backend execution",
    availability_status: DataAvailabilityStatus = "planned",
    supported_tile_formats: tuple[TileSourceFormat, ...] = ("geojson", "cog"),
    is_experimental: bool = False,
) -> LayerDefinition:
    return LayerDefinition(
        id=layer_id,
        name=name,
        short_name=short_name,
        group_id="derived",
        description=description,
        data_source=data_source,
        product_id=product_id,
        product_version=product_version,
        variable=variable,
        unit="score (0-100)",
        native_spatial_resolution=native_spatial_resolution,
        temporal_resolution="Multi-year",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "multi-year"),
        attribution=attribution,
        availability_status=availability_status,
        rendering_type="choropleth",
        supported_tile_formats=supported_tile_formats,
        qa_policy=qa_policy,
        limitations=limitations,
        color_ramp=RESILIENCE_RAMP,
        value_range=_RESILIENCE_VALUE_RANGE,
        legend=LegendConfiguration(
            title=legend_title,
            unit=legend_unit,
            min_label=min_label,
            mid_label="50",
            max_label=max_label,
            gradient_css=gradient_css,
            nodata_color="#d0dbe0",
            nodata_label=nodata_label,
            stops=RESILIENCE_RAMP,
        ),
        tile_source=MapTileSource(
            id=tile_source_id,
            format="geojson",
            url_template=None,
            crs="EPSG:4326",
            requires_backend_authorization=True,
            is_connected=False,
        ),
        is_experimental=is_experimental,
    )


RESILIENCE_LAYERS: tuple[LayerDefinition, ...] = (
    _build_resilience_layer(
        layer_id="resistance",
        name="Resistance",
        short_name="Resistance",
        description=(
            "Ecosystem resistance metric quantifying deflection magnitude relative to "
            "pre-disturbance baseline during an identified stress event."
        ),
        product_id="TERRA-RES-RESISTANCE",
        variable="resistance_index",
        legend_title="Ecosystem Resistance",
        min_label="0 · Low",
        max_label="100 · High",
        nodata_label="No stress event / Insufficient data",
        tile_source_id="src-resistance",
        qa_policy="Requires validated stress event window and >= 12 post-event observations",
        limitations="Requires backend event-response modeling.",
    ),
    _build_resilience_layer(
        layer_id="recovery",
        name="Recovery",
        short_name="Recovery",
        description=(
            "Post-disturbance ecosystem recovery rate and return toward baseline trajectory."
        ),
        product_id="TERRA-RES-RECOVERY",
        variable="recovery_index",
        legend_title="Ecosystem Recovery",
        min_label="0 · Slow",
        max_label="100 · Rapid",
        nodata_label="Withheld / Post-event window incomplete",
        tile_source_id="src-recovery",
        qa_policy="Requires >= 12 valid post-event months after disturbance peak",
        limitations="Requires backend recovery trajectory fitting.",
    ),
    _build_resilience_layer(
        layer_id="stability",
        name="Stability",
        short_name="Stability",
        description=(
            "Temporal invariability of seasonal ecosystem anomalies over the reference period."
        ),
        product_id="TERRA-RES-STABILITY",
        variable="stability_index",
        legend_title="Temporal Stability",
        min_label="0 · Volatile",
        max_label="100 · Stable",
        nodata_label="Insufficient observations",
        tile_source_id="src-stability",
        qa_policy="Requires >= 80% valid observations across full multi-year series",
        limitations=(
            "Does not distinguish managed agricultural variance from natural biome stability."
        ),
    ),
    _build_resilience_layer(
        layer_id="sensitivity",
        name="Sensitivity",
        short_name="Sensitivity",
        description=(
            "Empirical responsiveness of vegetation anomalies to concurrent thermal "
            "and hydroclimatic forcing anomalies."
        ),
        product_id="TERRA-RES-SENSITIVITY",
        variable="sensitivity_index",
        legend_title="Climate Sensitivity",
        min_label="0 · Buffered",
        max_label="100 · Sensitive",
        nodata_label="Insufficient matched observations",
        tile_source_id="src-sensitivity",
        native_spatial_resolution="AOI / Harmonized grid",
        gradient_css=_REVERSED_RESILIENCE_GRADIENT,
        qa_policy="Statistical coupling metric only; correlation does not establish causation",
        limitations="Lag structures vary across biomes and soil depths.",
    ),
    _build_resilience_layer(
        layer_id="experimental-tri",
        name="Experimental TRI",
        short_name="TRI (Exp.)",
        description=(
            "Experimental TERRA Resilience Index combining Resistance, Recovery, Stability, "
            "and Sensitivity. Provisional, versioned research model awaiting validation."
        ),
        data_source="TERRA Scientific Core · Experimental Model",
        product_id="TERRA-TRI-EXP",
        product_version="v0.1-experimental",
        variable="tri_composite",
        native_spatial_resolution="AOI / Region summary",
        legend_title="Experimental TRI",
        legend_unit="Experimental index (0-100)",
        min_label="0 · Fragile",
        max_label="100 · Resilient",
        nodata_label="Withheld · Eligibility gate",
        tile_source_id="src-experimental-tri",
        attribution="TERRA Experimental TRI v0.1 · Not for operational decisions",
        availability_status="unavailable",
        supported_tile_formats=("geojson",),
        qa_policy="Withheld if any component fails >= 80% valid-month eligibility gate",
        limitations=(
            "Experimental composite index; component weights and normalization are "
            "provisional until independently validated."
        ),
        is_experimental=True,
    ),
)
