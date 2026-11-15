"""Authoritative provider, product, and variable catalog for GHS endpoints and discovery."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from geospatial_harmonization.config.settings import Settings


@dataclass(frozen=True, slots=True)
class VariableCatalogSpec:
    """Catalog metadata describing a supported provider variable."""

    name: str
    units: str
    semantics: str
    description: str


@dataclass(frozen=True, slots=True)
class ProductCatalogSpec:
    """Catalog metadata describing a supported NASA or generic product."""

    product: str
    version: str
    title: str
    spatial_resolution: str
    temporal_resolution: str
    crs: str
    source_format: str
    variables: tuple[VariableCatalogSpec, ...]


@dataclass(frozen=True, slots=True)
class ProviderCatalogSpec:
    """Provider-level catalog and auth metadata (strictly non-secret)."""

    provider: str
    title: str
    auth_required: bool
    auth_mechanism: str
    products: tuple[ProductCatalogSpec, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Normalized observation discovery record returned by provider discover hooks."""

    observation_id: str
    provider: str
    product: str
    product_version: str
    title: str
    time_start: datetime | None = None
    time_end: datetime | None = None
    bbox: tuple[float, float, float, float] | None = None
    query_mode: str | None = None
    access_hint: str | None = None
    metadata: dict[str, object] | None = None


@runtime_checkable
class DiscoverableHandler(Protocol):
    """Optional capability for DataHandlers supporting AOI/time observation discovery."""

    async def discover(
        self,
        *,
        product: str,
        bbox: tuple[float, float, float, float],
        start_time: datetime,
        end_time: datetime,
        limit: int = 10,
    ) -> tuple[DiscoveryResult, ...]: ...


_MODIS_PRODUCTS: tuple[ProductCatalogSpec, ...] = (
    ProductCatalogSpec(
        product="MOD13Q1.061",
        version="061",
        title="MODIS/Terra Vegetation Indices 16-Day L3 Global 250m SIN Grid V061",
        spatial_resolution="250 m",
        temporal_resolution="16-day composite",
        crs="SR-ORG:6974 (MODIS Sinusoidal, R=6371007.181m)",
        source_format="hdf4",
        variables=(
            VariableCatalogSpec(
                "NDVI",
                "1",
                "continuous_intensive",
                "16-day Normalized Difference Vegetation Index (scale 0.0001)",
            ),
            VariableCatalogSpec(
                "EVI",
                "1",
                "continuous_intensive",
                "16-day Enhanced Vegetation Index (scale 0.0001)",
            ),
            VariableCatalogSpec(
                "pixel_reliability",
                "1",
                "qa_flag",
                "Summary pixel quality reliability rank (0=Good, 1=Marginal accepted)",
            ),
            VariableCatalogSpec(
                "vi_quality",
                "1",
                "qa_flag",
                "16-bit VI Quality bitmask (MODLAND, VI usefulness, aerosols, clouds)",
            ),
        ),
    ),
    ProductCatalogSpec(
        product="MOD11A2.061",
        version="061",
        title="MODIS/Terra Land Surface Temperature/Emissivity 8-Day L3 Global 1km V061",
        spatial_resolution="1000 m",
        temporal_resolution="8-day composite",
        crs="SR-ORG:6974 (MODIS Sinusoidal, R=6371007.181m)",
        source_format="hdf4",
        variables=(
            VariableCatalogSpec(
                "LST_Day_1km", "K", "continuous_intensive", "Daytime LST (scale 0.02 K)"
            ),
            VariableCatalogSpec(
                "LST_Night_1km", "K", "continuous_intensive", "Nighttime LST (scale 0.02 K)"
            ),
            VariableCatalogSpec("QC_Day", "1", "qa_flag", "Daytime LST QA bitmask"),
            VariableCatalogSpec("QC_Night", "1", "qa_flag", "Nighttime LST QA bitmask"),
        ),
    ),
)

_GPM_PRODUCTS: tuple[ProductCatalogSpec, ...] = tuple(
    ProductCatalogSpec(
        product=prod,
        version=prod.split(".")[-1],
        title=f"GPM IMERG Half-Hourly Precipitation ({run} run)",
        spatial_resolution="0.1 deg (~10 km)",
        temporal_resolution="30-min instantaneous rate",
        crs="EPSG:4326",
        source_format="hdf5 / netcdf4",
        variables=(
            VariableCatalogSpec(
                "precipitation",
                "mm/hour",
                "continuous_intensive",
                "Combined microwave-IR precipitation rate (mm/hour)",
            ),
            VariableCatalogSpec(
                "precipitationQualityIndex",
                "1",
                "qa_flag",
                "Precipitation quality index [0, 1]",
            ),
            VariableCatalogSpec(
                "probabilityLiquidPrecipitation",
                "%",
                "continuous_intensive",
                "Probability of liquid precipitation phase (%)",
            ),
        ),
    )
    for prod, run in (
        ("GPM_3IMERGHH.07", "Final V07"),
        ("GPM_3IMERGHH.06", "Final V06"),
        ("GPM_3IMERGHHE.07", "Early V07"),
        ("GPM_3IMERGHHL.07", "Late V07"),
    )
)

_SMAP_PRODUCTS: tuple[ProductCatalogSpec, ...] = (
    ProductCatalogSpec(
        product="SPL3SMP_E.006",
        version="006",
        title="SMAP Enhanced L3 Radiometer Global Daily 9 km Soil Moisture V006",
        spatial_resolution="9 km EASE-Grid 2.0 (36 km radiometer native footprint)",
        temporal_resolution="daily AM/PM overpasses",
        crs="EPSG:6933",
        source_format="hdf5",
        variables=(
            VariableCatalogSpec(
                "soil_moisture",
                "cm^3/cm^3",
                "continuous_intensive",
                "Retrieved volumetric surface soil moisture (0-5 cm)",
            ),
            VariableCatalogSpec(
                "retrieval_qual_flag",
                "1",
                "qa_flag",
                "SMAP soil moisture retrieval quality flag",
            ),
            VariableCatalogSpec(
                "surface_flag",
                "1",
                "qa_flag",
                "Surface condition bitmask (water, snow/ice, frozen ground)",
            ),
        ),
    ),
)

_POWER_VARS: tuple[VariableCatalogSpec, ...] = (
    VariableCatalogSpec(
        "PRECTOTCORR", "mm/day | mm/hour", "continuous_extensive", "Bias-corrected precipitation"
    ),
    VariableCatalogSpec("T2M", "degC", "continuous_intensive", "2-meter air temperature"),
    VariableCatalogSpec("T2M_MAX", "degC", "continuous_intensive", "Maximum 2-meter temperature"),
    VariableCatalogSpec("T2M_MIN", "degC", "continuous_intensive", "Minimum 2-meter temperature"),
    VariableCatalogSpec("RH2M", "%", "continuous_intensive", "2-meter relative humidity"),
    VariableCatalogSpec(
        "ALLSKY_SFC_SW_DWN",
        "MJ/m^2/day | MJ/hr",
        "continuous_intensive",
        "All-sky surface shortwave downward irradiance (CERES SYN1deg 1.0 deg)",
    ),
    VariableCatalogSpec("WS10M", "m/s", "continuous_intensive", "10-meter wind speed"),
)

_NASA_POWER_PRODUCTS: tuple[ProductCatalogSpec, ...] = tuple(
    ProductCatalogSpec(
        product=prod,
        version="2.x",
        title=f"NASA POWER Agroclimatology API ({cadence})",
        spatial_resolution="0.5 x 0.625 deg (MERRA-2 grid)",
        temporal_resolution=cadence,
        crs="EPSG:4326",
        source_format="json",
        variables=_POWER_VARS,
    )
    for prod, cadence in (
        ("power_daily", "daily"),
        ("power_hourly", "hourly"),
        ("nasa_power", "daily | hourly"),
    )
)

_GENERIC_PRODUCTS: tuple[ProductCatalogSpec, ...] = (
    ProductCatalogSpec(
        product="*",
        version="custom",
        title="Allowlisted direct HTTP/GeoTIFF/NetCDF/Zarr asset ingestion",
        spatial_resolution="source-native",
        temporal_resolution="source-native",
        crs="source-native",
        source_format="geotiff / netcdf / hdf5 / hdf4 / zarr",
        variables=(),
    ),
)

PROVIDER_CATALOG: dict[str, ProviderCatalogSpec] = {
    "modis": ProviderCatalogSpec(
        provider="modis",
        title="NASA LP DAAC MODIS Land Products",
        auth_required=True,
        auth_mechanism="earthdata_bearer_oauth",
        products=_MODIS_PRODUCTS,
    ),
    "gpm_imerg": ProviderCatalogSpec(
        provider="gpm_imerg",
        title="NASA GES DISC GPM IMERG Precipitation",
        auth_required=True,
        auth_mechanism="earthdata_bearer_oauth",
        products=_GPM_PRODUCTS,
    ),
    "smap": ProviderCatalogSpec(
        provider="smap",
        title="NASA NSIDC SMAP Enhanced Soil Moisture",
        auth_required=True,
        auth_mechanism="earthdata_bearer_oauth",
        products=_SMAP_PRODUCTS,
    ),
    "nasa_power": ProviderCatalogSpec(
        provider="nasa_power",
        title="NASA LaRC POWER Meteorological & Solar API",
        auth_required=False,
        auth_mechanism="public_none",
        products=_NASA_POWER_PRODUCTS,
    ),
    "generic": ProviderCatalogSpec(
        provider="generic",
        title="Generic Allowlisted Geospatial Asset Handler",
        auth_required=False,
        auth_mechanism="host_allowlist",
        products=_GENERIC_PRODUCTS,
    ),
}

ProviderHealthState = Literal["ready", "disabled", "missing_credentials", "restricted"]


@dataclass(frozen=True, slots=True)
class ProviderStatusSnapshot:
    """Secret-free runtime health and product summary for a registered provider."""

    provider: str
    title: str
    enabled: bool
    auth_required: bool
    auth_configured: bool
    auth_mechanism: str
    status: ProviderHealthState
    supports_discovery: bool
    registered_products: tuple[str, ...]
    products: tuple[ProductCatalogSpec, ...]


def build_provider_status_snapshots(
    settings: Settings,
    registered_capabilities: dict[str, tuple[str, ...]],
) -> tuple[ProviderStatusSnapshot, ...]:
    """Compute non-secret provider readiness and catalog metadata from Settings."""
    has_token = settings.has_earthdata_token()
    ordered = list(PROVIDER_CATALOG.keys())
    for key in sorted(registered_capabilities):
        if key not in PROVIDER_CATALOG:
            ordered.append(key)

    snapshots: list[ProviderStatusSnapshot] = []
    for prov in ordered:
        spec = PROVIDER_CATALOG.get(prov)
        enabled = settings.is_provider_enabled(prov)
        reg_products = registered_capabilities.get(prov, ())
        if spec is None:
            snapshots.append(
                ProviderStatusSnapshot(
                    provider=prov,
                    title=prov,
                    enabled=enabled,
                    auth_required=False,
                    auth_mechanism="none",
                    auth_configured=True,
                    status="ready" if enabled else "disabled",
                    supports_discovery=False,
                    registered_products=reg_products,
                    products=(),
                )
            )
            continue

        auth_configured = has_token if spec.auth_required else True
        if prov == "generic" and not enabled:
            state: ProviderHealthState = "restricted"
        elif not enabled:
            state = "disabled"
        elif spec.auth_required and not has_token:
            state = "missing_credentials"
        else:
            state = "ready"

        snapshots.append(
            ProviderStatusSnapshot(
                provider=spec.provider,
                title=spec.title,
                enabled=enabled,
                auth_required=spec.auth_required,
                auth_configured=auth_configured,
                auth_mechanism=spec.auth_mechanism,
                status=state,
                supports_discovery=prov != "generic",
                registered_products=reg_products,
                products=spec.products,
            )
        )
    return tuple(snapshots)
