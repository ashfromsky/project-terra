"""Application service for layer catalog, GHS raster enrichment, and proxy queries."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import httpx

from terra.modules.layers.domain.entities import (
    AvailableTimeRange,
    DataAvailabilityStatus,
    LayerDefinition,
    LegendConfiguration,
    MapLayerGroupId,
    MapTileSource,
    ObservationGranularity,
    TemporalCoverage,
)
from terra.modules.layers.domain.exceptions import (
    LayerDatasetUnavailableError,
    LayerNotFoundError,
    LayerRasterProxyError,
)
from terra.modules.layers.domain.repositories import LayerCatalogRepository

logger = logging.getLogger(__name__)

_RENDERABLE_FORMATS: frozenset[str] = frozenset({"geotiff", "hdf4", "hdf5", "netcdf", "zarr"})
_QA_NAME_TOKENS = ("qa", "qc", "qual", "flag", "reliability", "bitmask", "lat", "lon")

_STEPS_PER_YEAR: dict[ObservationGranularity, int] = {
    "16-day": 23,
    "8-day": 46,
    "daily": 365,
    "30-minute": 17_520,
    "monthly": 12,
    "multi-year": 12,
}


@dataclass(frozen=True, slots=True)
class _GhsLayerSpec:
    product_tokens: tuple[str, ...]
    variable_tokens: tuple[str, ...]
    default_variable: str
    colormap: str
    unit_conversion: str | None = None


_LAYER_GHS_SPECS: dict[str, _GhsLayerSpec] = {
    "ndvi-mod13q1": _GhsLayerSpec(
        product_tokens=("MOD13Q1", "MOD13"),
        variable_tokens=("ndvi",),
        default_variable="250m 16 days NDVI",
        colormap="ndvi",
    ),
    "evi-mod13q1": _GhsLayerSpec(
        product_tokens=("MOD13Q1", "MOD13"),
        variable_tokens=("evi",),
        default_variable="250m 16 days EVI",
        colormap="evi",
    ),
    "lst-mod11a2": _GhsLayerSpec(
        product_tokens=("MOD11A2", "MOD11"),
        variable_tokens=("lst_day", "lst"),
        default_variable="LST_Day_1km",
        colormap="lst_celsius",
        unit_conversion="kelvin_to_celsius",
    ),
    "lst-anomaly": _GhsLayerSpec(
        product_tokens=("TERRA-LST-ANOM", "MOD11C3", "LST-ANOM"),
        variable_tokens=("lst_anomaly", "lst_zscore", "anomaly"),
        default_variable="lst_anomaly",
        colormap="lst_celsius",
    ),
    "precip-gpm-imerg": _GhsLayerSpec(
        product_tokens=("GPM_3IMERG", "3IMERG", "IMERG"),
        variable_tokens=("precipitationcal", "precipitation", "precip"),
        default_variable="precipitationCal",
        colormap="precip",
    ),
    "soil-moisture-smap": _GhsLayerSpec(
        product_tokens=("SPL3SMP", "SMAP"),
        variable_tokens=("soil_moisture",),
        default_variable="soil_moisture",
        colormap="soil_moisture",
    ),
    "ndvi-anomaly": _GhsLayerSpec(
        product_tokens=("TERRA-NDVI-ANOM",),
        variable_tokens=("ndvi_zscore", "ndvi_anomaly", "anomaly"),
        default_variable="ndvi_zscore",
        colormap="viridis",
    ),
    "evi-anomaly": _GhsLayerSpec(
        product_tokens=("TERRA-EVI-ANOM",),
        variable_tokens=("evi_zscore", "evi_anomaly", "anomaly"),
        default_variable="evi_zscore",
        colormap="viridis",
    ),
    "vegetation-trend": _GhsLayerSpec(
        product_tokens=("TERRA-VEG-TREND",),
        variable_tokens=("ndvi_trend_per_decade", "trend"),
        default_variable="ndvi_trend_per_decade",
        colormap="viridis",
    ),
    "mann-kendall-significance": _GhsLayerSpec(
        product_tokens=("TERRA-MK-TEST",),
        variable_tokens=("mk_adjusted_pvalue", "pvalue", "mk"),
        default_variable="mk_adjusted_pvalue",
        colormap="viridis",
    ),
    "sens-slope": _GhsLayerSpec(
        product_tokens=("TERRA-SEN-SLOPE",),
        variable_tokens=("sens_slope", "slope"),
        default_variable="sens_slope",
        colormap="viridis",
    ),
    "resistance": _GhsLayerSpec(
        product_tokens=("TERRA-RES-RESISTANCE",),
        variable_tokens=("resistance_index", "resistance"),
        default_variable="resistance_index",
        colormap="viridis",
    ),
    "recovery": _GhsLayerSpec(
        product_tokens=("TERRA-RES-RECOVERY",),
        variable_tokens=("recovery_index", "recovery"),
        default_variable="recovery_index",
        colormap="viridis",
    ),
    "stability": _GhsLayerSpec(
        product_tokens=("TERRA-RES-STABILITY",),
        variable_tokens=("stability_index", "stability"),
        default_variable="stability_index",
        colormap="viridis",
    ),
    "sensitivity": _GhsLayerSpec(
        product_tokens=("TERRA-RES-SENSITIVITY",),
        variable_tokens=("sensitivity_index", "sensitivity"),
        default_variable="sensitivity_index",
        colormap="viridis",
    ),
}


def _match_variable_name(variables: object, tokens: tuple[str, ...]) -> str | None:
    if not isinstance(variables, Mapping):
        return None
    for raw_key in variables:
        key = str(raw_key)
        leaf = key.rsplit("/", 1)[-1].lower()
        if any(qa_tok in leaf for qa_tok in _QA_NAME_TOKENS):
            continue
        low = key.lower()
        if any(tok in low for tok in tokens):
            return key
    return None


def _extract_available_dates(
    dataset: Mapping[str, Any], tokens: tuple[str, ...]
) -> tuple[str, ...]:
    dates: set[str] = set()
    extensions = dataset.get("extensions")
    if isinstance(extensions, Mapping):
        ts_ext = extensions.get("time_series")
        if isinstance(ts_ext, Mapping):
            matched_entry: Mapping[str, Any] | None = None
            for raw_key, entry in ts_ext.items():
                if not isinstance(entry, Mapping):
                    continue
                low = str(raw_key).lower()
                if any(tok in low for tok in tokens):
                    matched_entry = entry
                    break
            if matched_entry is None:
                for entry in ts_ext.values():
                    if isinstance(entry, Mapping) and entry.get("timestamps"):
                        matched_entry = entry
                        break
            if matched_entry is not None:
                raw_ts = matched_entry.get("timestamps")
                if isinstance(raw_ts, list):
                    for item in raw_ts:
                        day = str(item)[:10]
                        if len(day) == 10 and day[4] == "-":
                            dates.add(day)

    if not dates:
        temporal = dataset.get("temporal_metadata")
        if isinstance(temporal, Mapping):
            for bound_key in ("start", "end"):
                raw_val = temporal.get(bound_key)
                if raw_val:
                    day = str(raw_val)[:10]
                    if len(day) == 10 and day[4] == "-":
                        dates.add(day)
                        break

    return tuple(sorted(dates))


def _valid_wgs84_bbox(raw: object) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        min_x, min_y, max_x, max_y = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if -180.0 <= min_x < max_x <= 180.0 and -90.0 <= min_y < max_y <= 90.0:
        return (min_x, min_y, max_x, max_y)
    return None


def _extract_wgs84_bbox(dataset: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    direct_bbox = _valid_wgs84_bbox(dataset.get("bbox_wgs84"))
    if direct_bbox is not None:
        return direct_bbox
    extensions = dataset.get("extensions")
    if isinstance(extensions, Mapping):
        summary = extensions.get("ingestion_summary")
        if isinstance(summary, Mapping):
            bbox = _valid_wgs84_bbox(summary.get("bbox_applied"))
            if bbox is not None:
                return bbox
    spatial = dataset.get("spatial_metadata")
    if isinstance(spatial, Mapping):
        bounds = spatial.get("bounds")
        crs = str(spatial.get("crs") or "")
        bbox = _valid_wgs84_bbox(bounds)
        if bbox is not None and ("4326" in crs or not crs):
            return bbox
    return None


def _dataset_sort_key(ds: Mapping[str, Any]) -> tuple[int, str, str]:
    raw_assets = ds.get("assets")
    formats = {
        str(a.get("data_format") or "").lower()
        for a in (raw_assets if isinstance(raw_assets, list) else [])
        if isinstance(a, Mapping)
    }
    if "geotiff" in formats:
        fmt_rank = 3
    elif formats & {"hdf4", "hdf5", "netcdf"}:
        fmt_rank = 2
    elif "zarr" in formats:
        fmt_rank = 1
    else:
        fmt_rank = 0
    temporal = ds.get("temporal_metadata")
    end_ts = ""
    if isinstance(temporal, Mapping):
        end_ts = str(temporal.get("end") or temporal.get("start") or "")
    return (fmt_rank, end_ts, str(ds.get("dataset_id") or ""))


def _select_matching_dataset(
    spec: _GhsLayerSpec,
    datasets: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool]:
    matching: list[dict[str, Any]] = []
    for ds in datasets:
        product = str(ds.get("product") or "").upper()
        if not any(tok.upper() in product for tok in spec.product_tokens):
            continue
        variables = ds.get("variables")
        if (
            isinstance(variables, Mapping)
            and variables
            and _match_variable_name(variables, spec.variable_tokens) is None
        ):
            continue
        matching.append(ds)

    if not matching:
        return None, False

    matching.sort(key=_dataset_sort_key, reverse=True)
    for ds in matching:
        raw_assets = ds.get("assets")
        formats = {
            str(a.get("data_format") or "").lower()
            for a in (raw_assets if isinstance(raw_assets, list) else [])
            if isinstance(a, Mapping)
        }
        if formats & _RENDERABLE_FORMATS:
            return ds, False
    return None, True


class LayerCatalogService:
    """Coordinates layer catalog discovery, live GHS enrichment, and raster proxying."""

    def __init__(
        self,
        repo: LayerCatalogRepository,
        *,
        ghs_base_url: str | None = None,
        ghs_timeout_seconds: float = 30.0,
        ghs_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._repo = repo
        self._ghs_base_url = ghs_base_url.rstrip("/") if ghs_base_url else None
        self._ghs_timeout_seconds = ghs_timeout_seconds
        self._ghs_transport = ghs_transport

    async def _fetch_ghs_datasets(self) -> tuple[list[dict[str, Any]], bool]:
        if not self._ghs_base_url:
            return [], False
        try:
            async with httpx.AsyncClient(
                base_url=self._ghs_base_url,
                timeout=self._ghs_timeout_seconds,
                transport=self._ghs_transport,
            ) as client:
                response = await client.get("/api/v1/datasets", params={"limit": 100})
                if response.status_code >= 400:
                    logger.warning(
                        "GHS dataset list returned status %s during layer enrichment.",
                        response.status_code,
                    )
                    return [], False
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Failed to query GHS datasets for layer enrichment: %s", exc)
            return [], False

        if not isinstance(payload, list):
            return [], False
        return [item for item in payload if isinstance(item, dict)], True

    def _enrich_layer(
        self,
        layer: LayerDefinition,
        datasets: list[dict[str, Any]],
        ghs_reachable: bool,
    ) -> LayerDefinition:
        base_layer = replace(
            layer,
            is_synthetic_preview=False,
            preview_property_key=None,
        )
        spec = _LAYER_GHS_SPECS.get(layer.id)
        if spec is None:
            return base_layer

        if not self._ghs_base_url:
            return base_layer

        if not ghs_reachable:
            return replace(
                base_layer,
                availability_status="unavailable",
                tile_source=replace(base_layer.tile_source, url_template=None, is_connected=False),
                unavailable_reason="Raster catalog service is temporarily unreachable.",
            )

        selected, has_only_non_raster = _select_matching_dataset(spec, datasets)
        if selected is None:
            reason = (
                "Dataset exists only in non-raster format (e.g. JSON/CSV) and cannot be "
                "directly rendered as raster tiles."
                if has_only_non_raster
                else (
                    base_layer.unavailable_reason
                    or f"No ingested {base_layer.product_id}.{base_layer.product_version} "
                    "raster dataset found in storage. Ingest observations via Data Sources."
                )
            )
            return replace(
                base_layer,
                tile_source=replace(base_layer.tile_source, url_template=None, is_connected=False),
                unavailable_reason=reason,
            )

        dataset_id = str(selected.get("dataset_id") or "")
        if not dataset_id:
            return base_layer

        raw_assets = selected.get("assets")
        formats = {
            str(a.get("data_format") or "").lower()
            for a in (raw_assets if isinstance(raw_assets, list) else [])
            if isinstance(a, Mapping)
        }
        has_geotiff = "geotiff" in formats
        has_only_zarr = "zarr" in formats and not (formats & {"geotiff", "hdf4", "hdf5", "netcdf"})
        tile_format = "cog" if has_geotiff else ("zarr" if has_only_zarr else "xyz")
        extensions = selected.get("extensions")
        is_aoi_scoped = isinstance(extensions, Mapping) and extensions.get("scope") == "aoi"
        status: DataAvailabilityStatus = "preview" if is_aoi_scoped else "connected"
        matched_var = (
            _match_variable_name(selected.get("variables"), spec.variable_tokens)
            or base_layer.variable
        )
        dates = _extract_available_dates(selected, spec.variable_tokens)
        bbox = _extract_wgs84_bbox(selected)

        units_map = selected.get("units")
        layer_unit = base_layer.unit
        if isinstance(units_map, Mapping):
            raw_unit = units_map.get(matched_var)
            if isinstance(raw_unit, str) and raw_unit.strip():
                if spec.unit_conversion == "kelvin_to_celsius" and raw_unit.strip().upper() in {
                    "K",
                    "KELVIN",
                    "KELVINS",
                }:
                    layer_unit = "°C"
                else:
                    layer_unit = raw_unit.strip()

        active_range = base_layer.available_time_range
        if dates:
            active_range = AvailableTimeRange(
                start=dates[0],
                end=dates[-1],
                cadence=base_layer.available_time_range.cadence,
            )

        return replace(
            base_layer,
            variable=matched_var,
            unit=layer_unit,
            available_time_range=active_range,
            availability_status=status,
            rendering_type="raster",
            tile_source=MapTileSource(
                id=base_layer.tile_source.id,
                format=tile_format,
                url_template=f"/api/v1/layers/{base_layer.id}/tiles/{{z}}/{{x}}/{{y}}.png",
                crs="EPSG:3857",
                requires_backend_authorization=False,
                is_connected=True,
            ),
            available_dates=dates,
            dataset_bbox=bbox,
            active_dataset_id=dataset_id,
            unavailable_reason=None,
        )

    async def list_layers(
        self,
        *,
        group_id: MapLayerGroupId | None = None,
        availability_status: DataAvailabilityStatus | None = None,
    ) -> list[LayerDefinition]:
        """Return catalog layers enriched with live GHS availability and matching filters."""
        catalog_layers = await self._repo.list_layers(
            group_id=group_id,
            availability_status=None,
        )
        datasets, ghs_reachable = await self._fetch_ghs_datasets()
        enriched = [self._enrich_layer(layer, datasets, ghs_reachable) for layer in catalog_layers]
        if availability_status is None:
            return enriched
        return [layer for layer in enriched if layer.availability_status == availability_status]

    async def get_layer(self, layer_id: str) -> LayerDefinition:
        """Return a single enriched layer definition or raise LayerNotFoundError."""
        layer = await self._repo.get_by_id(layer_id)
        if layer is None:
            raise LayerNotFoundError(f"Layer '{layer_id}' not found")
        datasets, ghs_reachable = await self._fetch_ghs_datasets()
        return self._enrich_layer(layer, datasets, ghs_reachable)

    async def get_legend(self, layer_id: str) -> tuple[LayerDefinition, LegendConfiguration]:
        """Return the layer and its legend configuration."""
        layer = await self.get_layer(layer_id)
        return layer, layer.legend

    async def get_coverage(self, layer_id: str) -> TemporalCoverage:
        """Return actual ingested temporal coverage or honest empty availability."""
        layer = await self.get_layer(layer_id)
        tr = layer.available_time_range
        start_year = int(tr.start[:4])
        end_year = int(tr.end[:4])
        years = max(1, end_year - start_year + 1)
        expected_steps = max(len(layer.available_dates), years * _STEPS_PER_YEAR[tr.cadence])
        if layer.active_dataset_id is not None and layer.tile_source.is_connected:
            available_steps = max(len(layer.available_dates), 1)
            coverage_pct = round(min(100.0, 100.0 * available_steps / max(expected_steps, 1)), 2)
            return TemporalCoverage(
                start_date=tr.start,
                end_date=tr.end,
                cadence=tr.cadence,
                total_expected_steps=expected_steps,
                available_steps=available_steps,
                coverage_percent=coverage_pct,
                notes=(
                    f"Connected to persisted dataset {layer.active_dataset_id} "
                    f"({available_steps} timestep(s) indexed)."
                ),
                is_simulated_coverage=False,
                available_dates=layer.available_dates,
                dataset_bbox=layer.dataset_bbox,
                active_dataset_id=layer.active_dataset_id,
            )

        return TemporalCoverage(
            start_date=tr.start,
            end_date=tr.end,
            cadence=tr.cadence,
            total_expected_steps=expected_steps,
            available_steps=0,
            coverage_percent=0.0,
            notes=layer.unavailable_reason
            or "No ingested observations found in storage for this layer.",
            is_simulated_coverage=False,
            available_dates=(),
            dataset_bbox=None,
            active_dataset_id=None,
        )

    def _resolve_proxy_context(
        self,
        layer: LayerDefinition,
        dataset_id: str | None,
    ) -> tuple[_GhsLayerSpec, str]:
        spec = _LAYER_GHS_SPECS.get(layer.id)
        if spec is None:
            raise LayerDatasetUnavailableError(
                layer.unavailable_reason
                or f"Layer '{layer.id}' has no direct raster visualization dataset."
            )
        target_dataset_id = dataset_id or layer.active_dataset_id
        if not target_dataset_id or not self._ghs_base_url:
            raise LayerDatasetUnavailableError(
                layer.unavailable_reason
                or f"No ingested dataset is currently available for layer '{layer.id}'."
            )
        return spec, target_dataset_id

    async def _proxy_ghs_get(
        self,
        path: str,
        params: dict[str, str | int | float],
    ) -> httpx.Response:
        if not self._ghs_base_url:
            raise LayerDatasetUnavailableError("Raster service URL is not configured.")
        try:
            async with httpx.AsyncClient(
                base_url=self._ghs_base_url,
                timeout=self._ghs_timeout_seconds,
                transport=self._ghs_transport,
            ) as client:
                response = await client.get(path, params=params)
        except httpx.HTTPError as exc:
            logger.warning("Raster proxy request failed on %s: %s", path, exc)
            raise LayerRasterProxyError(
                status_code=502,
                detail="Upstream raster service is unreachable.",
            ) from exc

        if response.status_code >= 400:
            detail = "Raster processing error."
            try:
                body = response.json()
                if isinstance(body, Mapping) and body.get("detail"):
                    detail = str(body["detail"])
            except ValueError:
                pass
            raise LayerRasterProxyError(status_code=response.status_code, detail=detail)
        return response

    async def render_layer_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        *,
        timestamp: str | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        dataset_id: str | None = None,
    ) -> bytes:
        """Render an XYZ RGBA PNG tile from the layer's active ingested raster dataset."""
        layer = await self.get_layer(layer_id)
        spec, target_dataset_id = self._resolve_proxy_context(layer, dataset_id)
        params: dict[str, str | int | float] = {
            "variable": layer.variable,
            "colormap": spec.colormap,
            "vmin": layer.value_range.default_min if vmin is None else vmin,
            "vmax": layer.value_range.default_max if vmax is None else vmax,
        }
        if timestamp:
            params["timestamp"] = timestamp
        if spec.unit_conversion:
            params["unit_conversion"] = spec.unit_conversion
        resp = await self._proxy_ghs_get(
            f"/api/v1/datasets/{target_dataset_id}/tiles/{z}/{x}/{y}.png",
            params,
        )
        return resp.content

    async def render_layer_image(
        self,
        layer_id: str,
        bbox: str,
        *,
        crs: str = "EPSG:4326",
        width: int = 512,
        height: int = 512,
        timestamp: str | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        dataset_id: str | None = None,
    ) -> bytes:
        """Render a bounding-box RGBA PNG image from the layer's active ingested raster dataset."""
        layer = await self.get_layer(layer_id)
        spec, target_dataset_id = self._resolve_proxy_context(layer, dataset_id)
        params: dict[str, str | int | float] = {
            "bbox": bbox,
            "crs": crs,
            "width": width,
            "height": height,
            "variable": layer.variable,
            "colormap": spec.colormap,
            "vmin": layer.value_range.default_min if vmin is None else vmin,
            "vmax": layer.value_range.default_max if vmax is None else vmax,
        }
        if timestamp:
            params["timestamp"] = timestamp
        if spec.unit_conversion:
            params["unit_conversion"] = spec.unit_conversion
        resp = await self._proxy_ghs_get(
            f"/api/v1/datasets/{target_dataset_id}/render.png",
            params,
        )
        return resp.content

    async def inspect_layer_point(
        self,
        layer_id: str,
        lon: float,
        lat: float,
        *,
        timestamp: str | None = None,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Query exact native-grid pixel value and QA metadata at WGS 84 (lon, lat)."""
        layer = await self.get_layer(layer_id)
        try:
            spec, target_dataset_id = self._resolve_proxy_context(layer, dataset_id)
        except LayerDatasetUnavailableError as exc:
            return {
                "layer_id": layer.id,
                "dataset_id": None,
                "product": layer.product_id,
                "variable": layer.variable,
                "lon": lon,
                "lat": lat,
                "timestamp": timestamp,
                "status": "unavailable",
                "value": None,
                "raw_value": None,
                "unit": layer.unit,
                "qa_value": None,
                "qa_passed": None,
                "crs": None,
                "nominal_resolution_m": None,
                "pixel_row": None,
                "pixel_col": None,
                "bbox": None,
                "time_series": [],
                "reason": str(exc),
            }

        params: dict[str, str | int | float] = {
            "lon": lon,
            "lat": lat,
            "variable": layer.variable,
        }
        if timestamp:
            params["timestamp"] = timestamp
        if spec.unit_conversion:
            params["unit_conversion"] = spec.unit_conversion

        try:
            resp = await self._proxy_ghs_get(
                f"/api/v1/datasets/{target_dataset_id}/point",
                params,
            )
            payload = resp.json()
        except LayerRasterProxyError as exc:
            if exc.status_code in (404, 422):
                raise
            return {
                "layer_id": layer.id,
                "dataset_id": target_dataset_id,
                "product": layer.product_id,
                "variable": layer.variable,
                "lon": lon,
                "lat": lat,
                "timestamp": timestamp,
                "status": "unavailable",
                "value": None,
                "raw_value": None,
                "unit": layer.unit,
                "qa_value": None,
                "qa_passed": None,
                "crs": None,
                "nominal_resolution_m": None,
                "pixel_row": None,
                "pixel_col": None,
                "bbox": None,
                "time_series": [],
                "reason": exc.detail,
            }

        if not isinstance(payload, dict):
            raise LayerRasterProxyError(status_code=502, detail="Invalid raster point response.")
        return {
            **payload,
            "layer_id": layer.id,
            "reason": None,
        }
