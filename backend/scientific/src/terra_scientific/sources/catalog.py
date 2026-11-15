"""Authoritative source-aware policies, variables, CRS, and QA specs for NASA EO products."""

from pydantic import BaseModel, ConfigDict, Field

from terra_scientific.domain.enums import (
    DataSourceId,
    QaPolicyLevel,
    TemporalCadence,
    TemporalSemantics,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import ScientificInputError, UnsupportedSourceError
from terra_scientific.domain.models.dataset import VariableMetadata
from terra_scientific.domain.models.quality import QaPolicySpec

MODIS_SINUSOIDAL_WKT = (
    'PROJCS["Sinusoidal",'
    'GEOGCS["GCS_Unknown",'
    'DATUM["D_Unknown",SPHEROID["User_Defined_Spheroid",6371007.181,0.0]],'
    'PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Sinusoidal"],'
    'PARAMETER["False_Easting",0.0],'
    'PARAMETER["False_Northing",0.0],'
    'PARAMETER["Central_Meridian",0.0],'
    'UNIT["Meter",1.0]]'
)
MODIS_SINUSOIDAL_PROJ4 = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"


class SourceProductSpec(BaseModel):
    """Authoritative metadata, grid support, QA rules, and physical limitations per product."""

    model_config = ConfigDict(frozen=True)

    source_id: DataSourceId
    product: str
    product_version: str
    provider: str
    default_variable: str
    native_crs: str
    nominal_resolution_m: float
    native_footprint_m: float | None = None
    temporal_cadence: TemporalCadence
    temporal_semantics: TemporalSemantics
    composite_days: int | None = None
    variables: dict[str, VariableMetadata]
    qa_policies: dict[QaPolicyLevel, QaPolicySpec]
    limitations: list[str] = Field(default_factory=list)
    reference: str


def _mod13q1_spec() -> SourceProductSpec:
    ndvi = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        add_offset=0.0,
        is_scaled=False,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
        description="MOD13Q1 250m 16-day Normalized Difference Vegetation Index",
    )
    evi = VariableMetadata(
        name="EVI",
        canonical_name="evi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        add_offset=0.0,
        is_scaled=False,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
        description="MOD13Q1 250m 16-day Enhanced Vegetation Index",
    )
    qa_policies = {
        QaPolicyLevel.STRICT: QaPolicySpec(
            policy_id="mod13q1_strict_v61",
            level=QaPolicyLevel.STRICT,
            source_id=DataSourceId.MODIS_MOD13Q1,
            product="MOD13Q1.061",
            product_version="061",
            description="Accepts pixel_reliability==0 (Good) and clean VI Quality MODLAND==00",
            accepted_flags=(0,),
            excluded_flags=(-1, 1, 2, 3),
            bitmask_rules={
                "pixel_reliability": {"accepted": [0], "rejected": [-1, 1, 2, 3]},
                "vi_quality": {
                    "max_modland": 0,
                    "max_usefulness": 2,
                    "reject_adjacent_cloud": True,
                    "reject_mixed_cloud": True,
                    "reject_snow_ice": True,
                    "reject_shadow": True,
                },
            },
            min_coverage_fraction=0.7,
            reference="https://modis-land.gsfc.nasa.gov/pdf/MOD13_User_Guide_V61.pdf",
        ),
        QaPolicyLevel.STANDARD: QaPolicySpec(
            policy_id="mod13q1_standard_v61",
            level=QaPolicyLevel.STANDARD,
            source_id=DataSourceId.MODIS_MOD13Q1,
            product="MOD13Q1.061",
            product_version="061",
            description="Accepts pixel_reliability in {0, 1} (Good/Marginal) without snow/cloud",
            accepted_flags=(0, 1),
            excluded_flags=(-1, 2, 3),
            bitmask_rules={
                "pixel_reliability": {"accepted": [0, 1], "rejected": [-1, 2, 3]},
                "vi_quality": {
                    "max_modland": 1,
                    "max_usefulness": 6,
                    "reject_adjacent_cloud": True,
                    "reject_mixed_cloud": True,
                    "reject_snow_ice": True,
                    "reject_shadow": True,
                },
            },
            min_coverage_fraction=0.6,
            reference="https://modis-land.gsfc.nasa.gov/pdf/MOD13_User_Guide_V61.pdf",
        ),
        QaPolicyLevel.PERMISSIVE: QaPolicySpec(
            policy_id="mod13q1_permissive_v61",
            level=QaPolicyLevel.PERMISSIVE,
            source_id=DataSourceId.MODIS_MOD13Q1,
            product="MOD13Q1.061",
            product_version="061",
            description="Accepts Good/Marginal and flags Snow/Ice for exploratory masking",
            accepted_flags=(0, 1),
            excluded_flags=(-1, 3),
            bitmask_rules={
                "pixel_reliability": {"accepted": [0, 1], "rejected": [-1, 2, 3]},
                "vi_quality": {"max_modland": 1, "max_usefulness": 10},
            },
            min_coverage_fraction=0.4,
            reference="https://modis-land.gsfc.nasa.gov/pdf/MOD13_User_Guide_V61.pdf",
        ),
    }
    return SourceProductSpec(
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="nasa_earthdata",
        default_variable="NDVI",
        native_crs=MODIS_SINUSOIDAL_WKT,
        nominal_resolution_m=250.0,
        native_footprint_m=250.0,
        temporal_cadence=TemporalCadence.SIXTEEN_DAY,
        temporal_semantics=TemporalSemantics.COMPOSITE,
        composite_days=16,
        variables={"NDVI": ndvi, "EVI": evi},
        qa_policies=qa_policies,
        limitations=[
            "NDVI can saturate over high-biomass dense vegetation canopies.",
            "NDVI and EVI are spectral vegetation indices, not direct biodiversity measurements.",
            "Vegetation index declines do not alone prove degradation; evaluate seasonally.",
            "16-day composites reflect best-observation dates within 16 days, not calendar months.",
        ],
        reference="https://modis-land.gsfc.nasa.gov/pdf/MOD13_User_Guide_V61.pdf",
    )


def _mod11a2_spec() -> SourceProductSpec:
    lst_day = VariableMetadata(
        name="LST_Day_1km",
        canonical_name="land_surface_temperature_day",
        units="K",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.02,
        add_offset=0.0,
        is_scaled=False,
        fill_values=(0.0,),
        valid_range=(150.0, 380.0),
        description="MOD11A2 Daytime Land Surface Temperature (1 km 8-day composite)",
    )
    lst_night = VariableMetadata(
        name="LST_Night_1km",
        canonical_name="land_surface_temperature_night",
        units="K",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.02,
        add_offset=0.0,
        is_scaled=False,
        fill_values=(0.0,),
        valid_range=(150.0, 380.0),
        description="MOD11A2 Nighttime Land Surface Temperature (1 km 8-day composite)",
    )
    qa_policies = {
        QaPolicyLevel.STRICT: QaPolicySpec(
            policy_id="mod11a2_strict_v61",
            level=QaPolicyLevel.STRICT,
            source_id=DataSourceId.MODIS_MOD11A2,
            product="MOD11A2.061",
            product_version="061",
            description=(
                "Mandatory QC bits 0-1 == 00 (good quality) and LST error <= 1K (bits 6-7 == 00)"
            ),
            bitmask_rules={"qc": {"max_mandatory_qa": 0, "max_lst_error_code": 0}},
            min_coverage_fraction=0.7,
            reference="https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf",
        ),
        QaPolicyLevel.STANDARD: QaPolicySpec(
            policy_id="mod11a2_standard_v61",
            level=QaPolicyLevel.STANDARD,
            source_id=DataSourceId.MODIS_MOD11A2,
            product="MOD11A2.061",
            product_version="061",
            description="Mandatory QC bits 0-1 in {00, 01} and average LST error <= 2K",
            bitmask_rules={"qc": {"max_mandatory_qa": 1, "max_lst_error_code": 1}},
            min_coverage_fraction=0.6,
            reference="https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf",
        ),
        QaPolicyLevel.PERMISSIVE: QaPolicySpec(
            policy_id="mod11a2_permissive_v61",
            level=QaPolicyLevel.PERMISSIVE,
            source_id=DataSourceId.MODIS_MOD11A2,
            product="MOD11A2.061",
            product_version="061",
            description="Mandatory QC bits 0-1 in {00, 01} allowing up to 3K LST error",
            bitmask_rules={"qc": {"max_mandatory_qa": 1, "max_lst_error_code": 2}},
            min_coverage_fraction=0.4,
            reference="https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf",
        ),
    }
    return SourceProductSpec(
        source_id=DataSourceId.MODIS_MOD11A2,
        product="MOD11A2.061",
        product_version="061",
        provider="nasa_earthdata",
        default_variable="LST_Day_1km",
        native_crs=MODIS_SINUSOIDAL_WKT,
        nominal_resolution_m=1000.0,
        native_footprint_m=1000.0,
        temporal_cadence=TemporalCadence.EIGHT_DAY,
        temporal_semantics=TemporalSemantics.COMPOSITE,
        composite_days=8,
        variables={"LST_Day_1km": lst_day, "LST_Night_1km": lst_night},
        qa_policies=qa_policies,
        limitations=[
            "Land Surface Temperature (radiometric skin temperature) is NOT 2 m air temperature.",
            (
                "Clear-sky thermal retrievals introduce clear-sky sampling bias relative to "
                "cloudy periods."
            ),
            "Daytime and nighttime LST channels must be analyzed independently.",
        ],
        reference="https://lpdaac.usgs.gov/documents/715/MOD11_User_Guide_V61.pdf",
    )


def _imerg_spec(version: str = "07") -> SourceProductSpec:
    var_name = "Grid/precipitation" if version == "07" else "precipitationCal"
    precip = VariableMetadata(
        name=var_name,
        canonical_name="precipitation_rate",
        units="mm/hr",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=1.0,
        add_offset=0.0,
        is_scaled=True,
        fill_values=(-9999.9, -9999.0),
        valid_range=(0.0, 400.0),
        description=f"GPM IMERG V{version} calibrated multi-satellite precipitation rate",
    )
    qa_policies = {
        QaPolicyLevel.STRICT: QaPolicySpec(
            policy_id=f"imerg_v{version}_strict",
            level=QaPolicyLevel.STRICT,
            source_id=DataSourceId.GPM_IMERG,
            product=f"GPM_3IMERGHH.{version}",
            product_version=version,
            description=(
                "Require precipitationQualityIndex >= 0.4 and >= 80% valid half-hour intervals"
            ),
            bitmask_rules={"min_pqi": 0.4},
            min_coverage_fraction=0.8,
            reference="https://gpm.nasa.gov/resources/documents/imerg-v07-technical-documentation",
        ),
        QaPolicyLevel.STANDARD: QaPolicySpec(
            policy_id=f"imerg_v{version}_standard",
            level=QaPolicyLevel.STANDARD,
            source_id=DataSourceId.GPM_IMERG,
            product=f"GPM_3IMERGHH.{version}",
            product_version=version,
            description="Require >= 70% valid intervals; PQI >= 0.1 when PQI layer supplied",
            bitmask_rules={"min_pqi": 0.1},
            min_coverage_fraction=0.7,
            reference="https://gpm.nasa.gov/resources/documents/imerg-v07-technical-documentation",
        ),
        QaPolicyLevel.PERMISSIVE: QaPolicySpec(
            policy_id=f"imerg_v{version}_permissive",
            level=QaPolicyLevel.PERMISSIVE,
            source_id=DataSourceId.GPM_IMERG,
            product=f"GPM_3IMERGHH.{version}",
            product_version=version,
            description="Minimum valid-range check with >= 50% temporal interval coverage",
            bitmask_rules={},
            min_coverage_fraction=0.5,
            reference="https://gpm.nasa.gov/resources/documents/imerg-v07-technical-documentation",
        ),
    }
    return SourceProductSpec(
        source_id=DataSourceId.GPM_IMERG,
        product=f"GPM_3IMERGHH.{version}",
        product_version=version,
        provider="nasa_earthdata",
        default_variable=var_name,
        native_crs="EPSG:4326",
        nominal_resolution_m=11132.0,
        native_footprint_m=11132.0,
        temporal_cadence=TemporalCadence.HALF_HOURLY,
        temporal_semantics=TemporalSemantics.INTERVAL,
        variables={var_name: precip},
        qa_policies=qa_policies,
        limitations=[
            (
                "Half-hourly IMERG values are intensive rates (mm/hr); "
                "multiply by 0.5 hr for depth (mm)."
            ),
            (
                "Final run is required for retrospective baselines; "
                "never mix Early/Late/Final silently."
            ),
            "Missing half-hour intervals must remain missing/NaN and never silently become 0 mm.",
            (
                "High-latitude snowfall and complex-terrain precipitation retrievals "
                "carry higher error."
            ),
        ],
        reference="https://gpm.nasa.gov/resources/documents/imerg-v07-technical-documentation",
    )


def _smap_spec() -> SourceProductSpec:
    sm_am = VariableMetadata(
        name="soil_moisture",
        canonical_name="surface_soil_moisture_am",
        units="cm^3/cm^3",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=1.0,
        add_offset=0.0,
        is_scaled=True,
        fill_values=(-9999.0,),
        valid_range=(0.02, 0.65),
        description="SMAP Enhanced L3 9km AM Surface Soil Moisture (top ~0-5 cm)",
    )
    sm_pm = VariableMetadata(
        name="soil_moisture_pm",
        canonical_name="surface_soil_moisture_pm",
        units="cm^3/cm^3",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=1.0,
        add_offset=0.0,
        is_scaled=True,
        fill_values=(-9999.0,),
        valid_range=(0.02, 0.65),
        description="SMAP Enhanced L3 9km PM Surface Soil Moisture (top ~0-5 cm)",
    )
    qa_policies = {
        QaPolicyLevel.STRICT: QaPolicySpec(
            policy_id="smap_spl3smp_e_006_strict",
            level=QaPolicyLevel.STRICT,
            source_id=DataSourceId.SMAP_SPL3SMP_E,
            product="SPL3SMP_E.006",
            product_version="006",
            description=(
                "Requires retrieval_qual_flag bit 0 == 0 (recommended) and surface_flag == 0"
            ),
            bitmask_rules={"require_recommended_bit0": True, "require_clean_surface": True},
            min_coverage_fraction=0.6,
            reference=(
                "https://nsidc.org/sites/default/files/documents/user-guide/spl3smp_e-v006-userguide.pdf"
            ),
        ),
        QaPolicyLevel.STANDARD: QaPolicySpec(
            policy_id="smap_spl3smp_e_006_standard",
            level=QaPolicyLevel.STANDARD,
            source_id=DataSourceId.SMAP_SPL3SMP_E,
            product="SPL3SMP_E.006",
            product_version="006",
            description=(
                "Allows retrieval_qual_flag == 0 or 8 (bit 0 == 0); blocks frozen/snow/water"
            ),
            bitmask_rules={"require_recommended_bit0": True, "allow_moderate_surface": True},
            min_coverage_fraction=0.5,
            reference=(
                "https://nsidc.org/sites/default/files/documents/user-guide/spl3smp_e-v006-userguide.pdf"
            ),
        ),
        QaPolicyLevel.PERMISSIVE: QaPolicySpec(
            policy_id="smap_spl3smp_e_006_permissive",
            level=QaPolicyLevel.PERMISSIVE,
            source_id=DataSourceId.SMAP_SPL3SMP_E,
            product="SPL3SMP_E.006",
            product_version="006",
            description=(
                "Excludes unattempted/failed bit0/bit1 retrievals while preserving range checks"
            ),
            bitmask_rules={"require_recommended_bit0": False},
            min_coverage_fraction=0.35,
            reference="https://nsidc.org/sites/default/files/documents/user-guide/spl3smp_e-v006-userguide.pdf",
        ),
    }
    return SourceProductSpec(
        source_id=DataSourceId.SMAP_SPL3SMP_E,
        product="SPL3SMP_E.006",
        product_version="006",
        provider="nasa_earthdata",
        default_variable="soil_moisture",
        native_crs="EPSG:6933",
        nominal_resolution_m=9000.0,
        native_footprint_m=36000.0,
        temporal_cadence=TemporalCadence.DAILY,
        temporal_semantics=TemporalSemantics.COMPOSITE,
        composite_days=1,
        variables={"soil_moisture": sm_am, "soil_moisture_pm": sm_pm},
        qa_policies=qa_policies,
        limitations=[
            (
                "Posted on a 9 km EASE-Grid 2.0 via Backus-Gilbert interpolation; "
                "native L-band footprint is ~36 km."
            ),
            "Senses top ~0-5 cm surface soil moisture only, not root-zone soil moisture.",
            (
                "AM (~06:00 local) and PM (~18:00 local) overpasses have different "
                "thermal/dielectric equilibria and must remain separate by default."
            ),
            (
                "Frozen soils, snow cover, open water, and dense vegetation (VWC > 5 kg/m^2) "
                "degrade accuracy."
            ),
        ],
        reference="https://nsidc.org/sites/default/files/documents/user-guide/spl3smp_e-v006-userguide.pdf",
    )


def _nasa_power_spec() -> SourceProductSpec:
    power_vars = {
        "T2M": VariableMetadata(
            name="T2M",
            canonical_name="air_temperature_2m",
            units="degC",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(-80.0, 60.0),
            description="2-meter Air Temperature",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "T2M_MAX": VariableMetadata(
            name="T2M_MAX",
            canonical_name="air_temperature_2m_max",
            units="degC",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(-80.0, 60.0),
            description="Maximum 2-meter Air Temperature",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "T2M_MIN": VariableMetadata(
            name="T2M_MIN",
            canonical_name="air_temperature_2m_min",
            units="degC",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(-90.0, 55.0),
            description="Minimum 2-meter Air Temperature",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "RH2M": VariableMetadata(
            name="RH2M",
            canonical_name="relative_humidity_2m",
            units="%",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(0.0, 100.0),
            description="2-meter Relative Humidity",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "PRECTOTCORR": VariableMetadata(
            name="PRECTOTCORR",
            canonical_name="bias_corrected_precipitation",
            units="mm/day",
            semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
            fill_values=(-999.0,),
            valid_range=(0.0, 1000.0),
            description="MERRA-2 Bias-Corrected Total Precipitation",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "ALLSKY_SFC_SW_DWN": VariableMetadata(
            name="ALLSKY_SFC_SW_DWN",
            canonical_name="surface_shortwave_irradiance",
            units="MJ/m^2/day",
            semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
            fill_values=(-999.0,),
            valid_range=(0.0, 45.0),
            description="All-Sky Surface Shortwave Downward Irradiance",
            attributes={"origin_dataset": "CERES_SYN1deg", "native_grid_deg": "1.0x1.0"},
        ),
        "WS2M": VariableMetadata(
            name="WS2M",
            canonical_name="wind_speed_2m",
            units="m/s",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(0.0, 75.0),
            description="2-meter Wind Speed",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
        "GWETTOP": VariableMetadata(
            name="GWETTOP",
            canonical_name="surface_soil_wetness",
            units="dimensionless",
            semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
            fill_values=(-999.0,),
            valid_range=(0.0, 1.0),
            description="MERRA-2 Surface Soil Wetness",
            attributes={"origin_dataset": "MERRA-2", "native_grid_deg": "0.5x0.625"},
        ),
    }
    qa_policies = {
        level: QaPolicySpec(
            policy_id=f"nasa_power_{level.value}",
            level=level,
            source_id=DataSourceId.NASA_POWER,
            product="POWER_DAILY",
            product_version="v10",
            description="Excludes -999.0 fill values and enforces meteorological physical bounds",
            min_coverage_fraction=0.8 if level == QaPolicyLevel.STRICT else 0.7,
            reference="https://power.larc.nasa.gov/docs/methodology/",
        )
        for level in QaPolicyLevel
    }
    return SourceProductSpec(
        source_id=DataSourceId.NASA_POWER,
        product="POWER_DAILY",
        product_version="v10",
        provider="nasa_power",
        default_variable="T2M",
        native_crs="EPSG:4326",
        nominal_resolution_m=55000.0,
        native_footprint_m=55000.0,
        temporal_cadence=TemporalCadence.DAILY,
        temporal_semantics=TemporalSemantics.INTERVAL,
        variables=power_vars,
        qa_policies=qa_policies,
        limitations=[
            (
                "Coarse global reanalysis/radiation grid: MERRA-2 (0.5x0.625 deg) and "
                "CERES SYN1deg (1.0x1.0 deg)."
            ),
            "Does not resolve local topography, microclimates, or sub-grid convective extremes.",
            (
                "Do not treat NASA POWER PRECTOTCORR as equivalent to or silent "
                "replacement for GPM IMERG."
            ),
        ],
        reference="https://power.larc.nasa.gov/docs/methodology/",
    )


SOURCE_REGISTRY: dict[tuple[DataSourceId, str], SourceProductSpec] = {
    (DataSourceId.MODIS_MOD13Q1, "MOD13Q1.061"): _mod13q1_spec(),
    (DataSourceId.MODIS_MOD11A2, "MOD11A2.061"): _mod11a2_spec(),
    (DataSourceId.GPM_IMERG, "GPM_3IMERGHH.07"): _imerg_spec("07"),
    (DataSourceId.GPM_IMERG, "GPM_3IMERGHH.06"): _imerg_spec("06"),
    (DataSourceId.SMAP_SPL3SMP_E, "SPL3SMP_E.006"): _smap_spec(),
    (DataSourceId.NASA_POWER, "POWER_DAILY"): _nasa_power_spec(),
}

_SOURCE_ALIASES: dict[DataSourceId, str] = {
    DataSourceId.MODIS_MOD13Q1: "MOD13Q1.061",
    DataSourceId.MODIS_MOD11A2: "MOD11A2.061",
    DataSourceId.GPM_IMERG: "GPM_3IMERGHH.07",
    DataSourceId.SMAP_SPL3SMP_E: "SPL3SMP_E.006",
    DataSourceId.NASA_POWER: "POWER_DAILY",
}


def assert_quantitative_source_allowed(source_id: DataSourceId, product: str = "") -> None:
    """Reject NASA GIBS browse imagery for quantitative computations."""
    if source_id == DataSourceId.NASA_GIBS or "gibs" in product.strip().lower():
        raise ScientificInputError(
            "NASA GIBS rendered tiles are contextual visualization layers only and must never "
            "be used as quantitative measurements.",
            code="gibs_quantitative_prohibited",
            details={"source_id": source_id.value, "product": product},
        )


def get_source_spec(source_id: DataSourceId, product: str | None = None) -> SourceProductSpec:
    """Resolve authoritative SourceProductSpec for a product identifier."""
    assert_quantitative_source_allowed(source_id, product or "")
    key_product = product or _SOURCE_ALIASES.get(source_id, "")
    spec = SOURCE_REGISTRY.get((source_id, key_product))
    if spec is None and key_product:
        upper = key_product.upper()
        for (sid, prod_key), candidate in SOURCE_REGISTRY.items():
            if sid == source_id and (prod_key.upper() == upper or prod_key.upper() in upper):
                return candidate
    if spec is None:
        default_key = _SOURCE_ALIASES.get(source_id)
        if default_key is not None and not product:
            return SOURCE_REGISTRY[(source_id, default_key)]
        raise UnsupportedSourceError(
            f"Unsupported source/product combination: {source_id.value} / {product!r}",
            code="unsupported_source",
        )
    return spec


def get_qa_policy(
    source_id: DataSourceId,
    product: str | None,
    level: QaPolicyLevel,
) -> QaPolicySpec:
    """Retrieve documented QA filtering policy for source/product/strictness level."""
    spec = get_source_spec(source_id, product)
    return spec.qa_policies[level]
