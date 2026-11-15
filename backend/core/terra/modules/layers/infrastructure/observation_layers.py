"""Observation layer definitions synchronized with frontend observation-layers.ts."""

from terra.modules.layers.domain.entities import (
    AvailableTimeRange,
    LayerDefinition,
    LegendConfiguration,
    MapTileSource,
    ValueRange,
)
from terra.modules.layers.infrastructure.color_ramps import (
    EVI_RAMP,
    PRECIP_ANOMALY_RAMP,
    SOIL_MOISTURE_RAMP,
    THERMAL_ABS_RAMP,
    THERMAL_TREND_RAMP,
    VEGETATION_RAMP,
)

OBSERVATION_LAYERS: tuple[LayerDefinition, ...] = (
    LayerDefinition(
        id="ndvi-mod13q1",
        name="NDVI · MOD13Q1.061",
        short_name="NDVI",
        group_id="vegetation",
        description=(
            "Normalized Difference Vegetation Index 16-day composite at 250 m native resolution "
            "from MODIS Terra."
        ),
        data_source="NASA LP DAAC · MODIS Terra",
        product_id="MOD13Q1",
        product_version="061",
        variable="250m 16 days NDVI",
        unit="NDVI (0-1)",
        native_spatial_resolution="250 m",
        temporal_resolution="16-day composite",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "16-day"),
        attribution="NASA LP DAAC · MOD13Q1 v061",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz"),
        qa_policy="MOD13Q1 Pixel Reliability == 0 (Good data) & VI Quality bitmask screening",
        limitations=(
            "Optical composite affected by persistent tropical cloud cover; "
            "saturates in very high-biomass canopies."
        ),
        color_ramp=VEGETATION_RAMP,
        value_range=ValueRange(-0.2, 1.0, 0.0, 1.0, 0.05),
        legend=LegendConfiguration(
            title="Vegetation Index (NDVI)",
            unit="NDVI (0-1)",
            min_label="0.0",
            mid_label="0.5",
            max_label="1.0",
            gradient_css=(
                "linear-gradient(90deg, #dfb892 0%, #e7dfba 32%, #a2d4b4 68%, #159b91 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="NoData / QA masked",
            stops=VEGETATION_RAMP,
        ),
        tile_source=MapTileSource(
            "src-mod13q1-ndvi",
            "wmts",
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_L3_NDVI_16Day/default/{time}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png",
            "EPSG:4326",
            False,
            False,
        ),
        is_synthetic_preview=False,
        preview_property_key=None,
        unavailable_reason=(
            "No ingested MOD13Q1.061 NDVI dataset found in storage. "
            "Ingest observations via Data Sources."
        ),
    ),
    LayerDefinition(
        id="evi-mod13q1",
        name="EVI · MOD13Q1.061",
        short_name="EVI",
        group_id="vegetation",
        description=(
            "Enhanced Vegetation Index reducing atmospheric aerosol and soil background noise "
            "in dense canopies."
        ),
        data_source="NASA LP DAAC · MODIS Terra",
        product_id="MOD13Q1",
        product_version="061",
        variable="250m 16 days EVI",
        unit="EVI (0-0.8)",
        native_spatial_resolution="250 m",
        temporal_resolution="16-day composite",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "16-day"),
        attribution="NASA LP DAAC · MOD13Q1 v061",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz"),
        qa_policy="VI Usefulness <= 2; snow/ice & adjacent cloud bits excluded",
        limitations="Sensitive to topographic slope effects in steep mountainous terrain.",
        color_ramp=EVI_RAMP,
        value_range=ValueRange(-0.2, 1.0, 0.0, 0.8, 0.05),
        legend=LegendConfiguration(
            title="Enhanced Vegetation (EVI)",
            unit="EVI (0-0.8)",
            min_label="0.0",
            mid_label="0.4",
            max_label="0.8",
            gradient_css=(
                "linear-gradient(90deg, #e5cbb0 0%, #dce4c2 35%, #8ec7be 70%, #0e7c74 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="NoData / QA masked",
            stops=EVI_RAMP,
        ),
        tile_source=MapTileSource(
            "src-mod13q1-evi",
            "wmts",
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_L3_EVI_16Day/default/{time}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png",
            "EPSG:4326",
            False,
            False,
        ),
        is_synthetic_preview=False,
        preview_property_key=None,
        unavailable_reason=(
            "No ingested MOD13Q1.061 EVI dataset found in storage. "
            "Ingest observations via Data Sources."
        ),
    ),
    LayerDefinition(
        id="lst-mod11a2",
        name="Land Surface Temperature · MOD11A2.061",
        short_name="LST Day",
        group_id="temperature",
        description=(
            "8-day clear-sky daytime Land Surface Temperature from MODIS Terra at 1 km native "
            "resolution (not equivalent to 2 m air temperature)."
        ),
        data_source="NASA LP DAAC · MODIS Terra",
        product_id="MOD11A2",
        product_version="061",
        variable="LST_Day_1km",
        unit="°C",
        native_spatial_resolution="1 km",
        temporal_resolution="8-day composite",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "8-day"),
        attribution="NASA LP DAAC · MOD11A2 v061",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz"),
        qa_policy="Mandatory QA == Good / Average LST error <= 1 K; scale 0.02 K -> °C",
        limitations="Clear-sky radiometric skin temperature bias; cloud-covered days are absent.",
        color_ramp=THERMAL_ABS_RAMP,
        value_range=ValueRange(-30, 60, -10, 45, 1),
        legend=LegendConfiguration(
            title="Land Surface Temperature",
            unit="°C (Daytime)",
            min_label="-10°C",
            mid_label="+18°C",
            max_label="+45°C",
            gradient_css=(
                "linear-gradient(90deg, #3193ce 0%, #a4cfca 35%, #ead6bc 70%, #c77f6d 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="Cloud / NoData",
            stops=THERMAL_ABS_RAMP,
        ),
        tile_source=MapTileSource(
            "src-mod11a2-lst",
            "wmts",
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_Land_Surface_Temp_Day/default/{time}/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png",
            "EPSG:4326",
            False,
            False,
        ),
        unavailable_reason=(
            "No ingested MOD11A2.061 daytime LST dataset found in storage. "
            "Ingest observations via Data Sources."
        ),
    ),
    LayerDefinition(
        id="lst-anomaly",
        name="LST Anomaly",
        short_name="LST Anomaly",
        group_id="temperature",
        description=(
            "Decadal or seasonal Land Surface Temperature anomaly relative to baseline "
            "climatology derived from scientific assessments."
        ),
        data_source="NASA LP DAAC · MOD11A2 / MOD11C3",
        product_id="MOD11A2 / MOD11C3",
        product_version="061",
        variable="LST_Anomaly",
        unit="°C / decade",
        native_spatial_resolution="1 km / 0.05° CMG",
        temporal_resolution="Monthly composite",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "monthly"),
        attribution="NASA LP DAAC · MOD11A2 / MOD11C3",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz"),
        qa_policy="Baseline 2001-2010 same-calendar-month anomaly; >= 80% valid months",
        limitations=(
            "Surface skin temperature trend is not directly interchangeable "
            "with meteorological air temperature."
        ),
        color_ramp=THERMAL_TREND_RAMP,
        value_range=ValueRange(-1.0, 1.5, -0.4, 0.8, 0.05),
        legend=LegendConfiguration(
            title="LST Trend / Anomaly",
            unit="°C / decade",
            min_label="-0.4",
            mid_label="0",
            max_label="+0.8",
            gradient_css=(
                "linear-gradient(90deg, #3193ce 0%, #a4cfca 35%, "
                "#e8e9db 50%, #deb49f 75%, #c77f6d 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="Insufficient valid months",
            stops=THERMAL_TREND_RAMP,
        ),
        tile_source=MapTileSource("src-lst-anomaly", "cog", None, "EPSG:4326", True, False),
        is_synthetic_preview=False,
        preview_property_key=None,
        unavailable_reason="No spatially gridded LST anomaly artifact is currently available.",
    ),
    LayerDefinition(
        id="precip-gpm-imerg",
        name="Precipitation · GPM IMERG V07",
        short_name="Precipitation",
        group_id="water",
        description=(
            "GPM IMERG Final Run gauge-calibrated precipitation estimate converted from interval "
            "rates to accumulated depth."
        ),
        data_source="NASA GES DISC · GPM",
        product_id="GPM_3IMERGHH",
        product_version="V07",
        variable="precipitationCal",
        unit="mm / hr",
        native_spatial_resolution="0.1° (~10 km)",
        temporal_resolution="30-min / Monthly sum",
        available_time_range=AvailableTimeRange("2001-01-01", "2025-12-31", "monthly"),
        attribution="NASA GES DISC · GPM IMERG V07",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz", "zarr"),
        qa_policy="Final Run V07; interval mm/hr rate integrated to mm depth before monthly sum",
        limitations=(
            "Lower accuracy over complex orographic snow/ice regions (>60° latitude); "
            "distinct from NASA POWER."
        ),
        color_ramp=PRECIP_ANOMALY_RAMP,
        value_range=ValueRange(0, 100, 0, 25, 1),
        legend=LegendConfiguration(
            title="Precipitation Rate",
            unit="mm / hr",
            min_label="0",
            mid_label="12.5",
            max_label="25",
            gradient_css=(
                "linear-gradient(90deg, #c77f6d 0%, #ead6bc 34%, "
                "#e8eef0 50%, #91c6bc 76%, #3193ce 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="NoData / High-latitude snow mask",
            stops=PRECIP_ANOMALY_RAMP,
        ),
        tile_source=MapTileSource(
            "src-gpm-imerg",
            "wmts",
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/IMERG_Precipitation_Rate/default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png",
            "EPSG:4326",
            False,
            False,
        ),
        is_synthetic_preview=False,
        preview_property_key=None,
        unavailable_reason=(
            "No ingested GPM IMERG V07 precipitation dataset found in storage. "
            "Ingest observations via Data Sources."
        ),
    ),
    LayerDefinition(
        id="soil-moisture-smap",
        name="Soil Moisture · SMAP SPL3SMP_E",
        short_name="Soil Moisture",
        group_id="water",
        description=(
            "SMAP Enhanced L3 Radiometer surface soil moisture (~0-5 cm depth) on 9 km "
            "EASE-Grid 2.0. Does not directly measure deep root-zone moisture."
        ),
        data_source="NASA NSIDC DAAC · SMAP",
        product_id="SPL3SMP_E",
        product_version="006",
        variable="soil_moisture",
        unit="cm³ / cm³",
        native_spatial_resolution="9 km (EASE-Grid 2.0)",
        temporal_resolution="Daily (AM/PM)",
        available_time_range=AvailableTimeRange("2015-03-31", "2025-12-31", "daily"),
        attribution="NASA NSIDC DAAC · SMAP SPL3SMP_E",
        availability_status="unavailable",
        rendering_type="raster",
        supported_tile_formats=("cog", "xyz", "zarr"),
        qa_policy=(
            "Retrieval quality bit 0 (recommended); frozen soil, water, "
            "and high VWC (>5 kg/m²) excluded"
        ),
        limitations=(
            "Measures top ~5 cm surface layer only; coverage begins March 31, 2015; "
            "degraded under dense tropical canopy."
        ),
        color_ramp=SOIL_MOISTURE_RAMP,
        value_range=ValueRange(0.0, 0.6, 0.02, 0.55, 0.02),
        legend=LegendConfiguration(
            title="Surface Soil Moisture",
            unit="cm³ / cm³",
            min_label="0.02",
            mid_label="0.28",
            max_label="0.55",
            gradient_css=(
                "linear-gradient(90deg, #deb49f 0%, #e8e9db 33%, #91c6bc 66%, #3193ce 100%)"
            ),
            nodata_color="#d0dbe0",
            nodata_label="Frozen / Dense canopy / RFI masked",
            stops=SOIL_MOISTURE_RAMP,
        ),
        tile_source=MapTileSource(
            "src-smap-spl3smp-e",
            "wmts",
            "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/SMAP_L3_Passive_Enhanced_Day_Soil_Moisture/default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png",
            "EPSG:4326",
            False,
            False,
        ),
        unavailable_reason=(
            "No ingested SMAP SPL3SMP_E.006 soil moisture dataset found in storage. "
            "Ingest observations via Data Sources."
        ),
    ),
)
