"""Adapters mapping GHS prepared dataset payloads and artifacts into Scientific Core."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import (
    DataSourceId,
    OverpassMode,
    TemporalCadence,
    TemporalSemantics,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.dataset import (
    ObservationSeries,
    ScientificDataset,
    ScientificGridStack,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.temporal import TemporalMetadata
from terra_scientific.sources.catalog import (
    SourceProductSpec,
    assert_quantitative_source_allowed,
    get_source_spec,
)


def _resolve_source_id(raw_source_id: str, product: str, provider: str) -> DataSourceId:
    combined = f"{raw_source_id} {product} {provider}".lower()
    if "gibs" in combined:
        return DataSourceId.NASA_GIBS
    if "mod13" in combined or "vegetation" in combined:
        return DataSourceId.MODIS_MOD13Q1
    if "mod11" in combined or "lst" in combined:
        return DataSourceId.MODIS_MOD11A2
    if "imerg" in combined or "gpm" in combined:
        return DataSourceId.GPM_IMERG
    if "smap" in combined or "spl3smp" in combined:
        return DataSourceId.SMAP_SPL3SMP_E
    if "power" in combined:
        return DataSourceId.NASA_POWER
    return DataSourceId.CUSTOM


def _parse_datetime(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if default is not None:
        return default
    raise ScientificInputError(f"Expected ISO-8601 timestamp string or datetime, got {value!r}")


def _resolve_cadence(raw: Any) -> TemporalCadence:
    value = str(raw or "").strip().lower()
    mapping = {
        "half_hourly": TemporalCadence.HALF_HOURLY,
        "30min": TemporalCadence.HALF_HOURLY,
        "hourly": TemporalCadence.HOURLY,
        "daily": TemporalCadence.DAILY,
        "1d": TemporalCadence.DAILY,
        "eight_day": TemporalCadence.EIGHT_DAY,
        "8d": TemporalCadence.EIGHT_DAY,
        "sixteen_day": TemporalCadence.SIXTEEN_DAY,
        "16d": TemporalCadence.SIXTEEN_DAY,
        "monthly": TemporalCadence.MONTHLY,
        "1m": TemporalCadence.MONTHLY,
        "seasonal": TemporalCadence.SEASONAL,
        "annual": TemporalCadence.ANNUAL,
    }
    return mapping.get(value, TemporalCadence.CUSTOM)


def _resolve_temporal_semantics(raw: Any) -> TemporalSemantics:
    value = str(raw or "interval").strip().lower()
    mapping = {
        "instantaneous": TemporalSemantics.INSTANTANEOUS,
        "interval": TemporalSemantics.INTERVAL,
        "composite": TemporalSemantics.COMPOSITE,
        "climatology": TemporalSemantics.CLIMATOLOGY,
    }
    return mapping.get(value, TemporalSemantics.INTERVAL)


_CANONICAL_ALIAS_MAP: dict[str, str] = {
    "250m 16 days NDVI": "NDVI",
    "250m_16_days_NDVI": "NDVI",
    "NDVI": "NDVI",
    "250m 16 days EVI": "EVI",
    "250m_16_days_EVI": "EVI",
    "EVI": "EVI",
    "Grid/precipitation": "precipitation",
    "precipitationCal": "precipitation",
    "precipitation": "precipitation",
    "Soil_Moisture_Retrieval_Data_AM/soil_moisture": "soil_moisture",
    "soil_moisture": "soil_moisture",
    "Soil_Moisture_Retrieval_Data_PM/soil_moisture_pm": "soil_moisture_pm",
    "soil_moisture_pm": "soil_moisture_pm",
}


def _resolve_catalog_var(
    name: str,
    catalog_spec: SourceProductSpec | None,
) -> VariableMetadata | None:
    if catalog_spec is None:
        return None
    direct = catalog_spec.variables.get(name)
    if direct is not None:
        return direct
    canonical = _CANONICAL_ALIAS_MAP.get(name, name)
    for candidate, target in _CANONICAL_ALIAS_MAP.items():
        if target == canonical and candidate in catalog_spec.variables:
            return catalog_spec.variables[candidate]
    return catalog_spec.variables.get(canonical)


def _optional_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    return float(value)


def _float_or_default(value: Any, default: float) -> float:
    if value is None:
        return default
    return float(value)


def _map_variable_spec(
    name: str,
    raw_spec: Mapping[str, Any],
    catalog_spec: SourceProductSpec | None,
) -> VariableMetadata:
    catalog_var = _resolve_catalog_var(name, catalog_spec)
    scale_factor = _float_or_default(
        raw_spec.get("scale_factor"),
        catalog_var.scale_factor if catalog_var else 1.0,
    )
    add_offset = _float_or_default(
        raw_spec.get("add_offset"),
        catalog_var.add_offset if catalog_var else 0.0,
    )

    attrs = dict(raw_spec.get("attributes") or {})
    str_attrs = {str(k): str(v) for k, v in attrs.items()}
    dtype_str = str(raw_spec.get("dtype") or "float64").lower()
    explicit_scaled = attrs.get("is_scaled")
    if explicit_scaled is not None:
        is_scaled = bool(explicit_scaled)
    elif "int" in dtype_str and (scale_factor != 1.0 or add_offset != 0.0):
        is_scaled = False
    else:
        is_scaled = True

    fill_vals: list[float] = []
    nodata_val = _optional_float(raw_spec.get("nodata"))
    if nodata_val is not None:
        fill_vals.append(nodata_val)
    if catalog_var is not None:
        for val in catalog_var.fill_values:
            if val not in fill_vals:
                fill_vals.append(val)

    raw_range = raw_spec.get("valid_range")
    valid_range: tuple[float, float] | None = None
    if catalog_var and catalog_var.valid_range is not None:
        valid_range = catalog_var.valid_range
    elif (
        isinstance(raw_range, list | tuple)
        and len(raw_range) == 2
        and raw_range[0] is not None
        and raw_range[1] is not None
    ):
        low, high = float(raw_range[0]), float(raw_range[1])
        if scale_factor != 1.0 or add_offset != 0.0:
            low = low * scale_factor + add_offset
            high = high * scale_factor + add_offset
        valid_range = (min(low, high), max(low, high))

    semantics_raw = str(raw_spec.get("semantics") or "continuous_intensive").lower()
    sem_map = {
        "continuous_intensive": VariableSemanticKind.CONTINUOUS_INTENSIVE,
        "continuous_extensive": VariableSemanticKind.CONTINUOUS_EXTENSIVE,
        "categorical": VariableSemanticKind.CATEGORICAL,
        "qa_flag": VariableSemanticKind.QA_FLAG,
        "coordinate": VariableSemanticKind.COORDINATE,
    }
    sem_kind = sem_map.get(
        semantics_raw,
        catalog_var.semantic_kind if catalog_var else VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    canonical = (
        catalog_var.canonical_name if catalog_var else name.lower().replace("/", "_").strip("_")
    )
    units = str(raw_spec.get("units") or (catalog_var.units if catalog_var else "dimensionless"))
    return VariableMetadata(
        name=name,
        canonical_name=canonical,
        units=units,
        semantic_kind=sem_kind,
        scale_factor=scale_factor,
        add_offset=add_offset,
        is_scaled=is_scaled,
        fill_values=tuple(fill_vals),
        valid_range=valid_range,
        description=catalog_var.description if catalog_var else "",
        attributes={**(catalog_var.attributes if catalog_var else {}), **str_attrs},
    )


def map_ghs_dataset_payload(payload: Mapping[str, Any]) -> ScientificDataset:
    """Convert a GHS `SpatialDataset` / `DatasetOut` JSON dictionary into ScientificDataset."""
    raw_source = str(payload.get("source_id", ""))
    product = str(payload.get("product", ""))
    provider = str(payload.get("provider", ""))
    source_id = _resolve_source_id(raw_source, product, provider)
    assert_quantitative_source_allowed(source_id, product)

    catalog_spec: SourceProductSpec | None = None
    if source_id != DataSourceId.CUSTOM:
        try:
            catalog_spec = get_source_spec(source_id, product or None)
        except ScientificInputError:
            catalog_spec = None

    extensions = dict(payload.get("extensions") or {})
    provenance = dict(payload.get("provenance") or {})
    spatial_raw = dict(payload.get("spatial_metadata") or {})
    temporal_raw = dict(payload.get("temporal_metadata") or {})

    raw_variables = dict(payload.get("variables") or {})
    has_catalog_raw_vars = catalog_spec is not None and any(
        _resolve_catalog_var(vname, catalog_spec) is not None for vname in raw_variables
    )
    mapped_vars: dict[str, VariableMetadata] = {}
    for var_name, raw_var in raw_variables.items():
        if isinstance(raw_var, Mapping):
            if has_catalog_raw_vars and _resolve_catalog_var(var_name, catalog_spec) is None:
                sem = str(raw_var.get("semantics") or "").lower()
                if sem not in {"qa_flag", "coordinate"}:
                    continue
            mapped = _map_variable_spec(var_name, raw_var, catalog_spec)
            mapped_vars[var_name] = mapped
            canonical_alias = _CANONICAL_ALIAS_MAP.get(var_name)
            if canonical_alias and canonical_alias not in mapped_vars:
                mapped_vars[canonical_alias] = mapped.model_copy(update={"name": canonical_alias})

    if not mapped_vars and catalog_spec is not None:
        mapped_vars = dict(catalog_spec.variables)
        for cat_name, cat_var in list(mapped_vars.items()):
            canonical_alias = _CANONICAL_ALIAS_MAP.get(cat_name)
            if canonical_alias and canonical_alias not in mapped_vars:
                mapped_vars[canonical_alias] = cat_var.model_copy(update={"name": canonical_alias})

    now_utc = datetime.now(UTC)
    t_start = _parse_datetime(temporal_raw.get("start"), default=now_utc)
    t_end = _parse_datetime(temporal_raw.get("end"), default=t_start)
    cadence = _resolve_cadence(
        temporal_raw.get("cadence")
        or (catalog_spec.temporal_cadence.value if catalog_spec else "custom")
    )
    t_sem = _resolve_temporal_semantics(
        temporal_raw.get("semantics")
        or (catalog_spec.temporal_semantics.value if catalog_spec else "interval")
    )
    composite_days_raw = temporal_raw.get(
        "composite_days",
        catalog_spec.composite_days if catalog_spec else None,
    )
    composite_days = int(composite_days_raw) if composite_days_raw is not None else None
    if t_sem == TemporalSemantics.COMPOSITE and composite_days is None:
        composite_days = 1

    temporal_meta = TemporalMetadata(
        cadence=cadence,
        semantics=t_sem,
        start=t_start,
        end=t_end,
        composite_days=composite_days,
    )

    crs = str(spatial_raw.get("crs") or (catalog_spec.native_crs if catalog_spec else "EPSG:4326"))
    nom_res = _optional_float(spatial_raw.get("nominal_resolution_m"))
    if nom_res is None:
        nom_res = _optional_float(spatial_raw.get("resolution_x"))
    if nom_res is None and catalog_spec is not None:
        nom_res = catalog_spec.nominal_resolution_m
    nom_res_f = abs(nom_res) if nom_res is not None else None
    if nom_res_f is not None and nom_res_f <= 0.0:
        nom_res_f = None

    raw_bounds = spatial_raw.get("bounds")
    bounds_tuple: tuple[float, float, float, float] | None = None
    if (
        isinstance(raw_bounds, list | tuple)
        and len(raw_bounds) == 4
        and all(b is not None for b in raw_bounds)
    ):
        bounds_tuple = (
            float(raw_bounds[0]),
            float(raw_bounds[1]),
            float(raw_bounds[2]),
            float(raw_bounds[3]),
        )

    spatial_support = SpatialSupport(
        crs=crs,
        nominal_resolution_m=nom_res_f,
        native_footprint_m=catalog_spec.native_footprint_m if catalog_spec else nom_res_f,
        bounds=bounds_tuple,
        is_projected="epsg:4326" not in crs.lower(),
    )

    raster_refs: dict[str, str] = {}
    assets = list(payload.get("assets") or [])
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        ref = str(asset.get("storage_key") or asset.get("uri") or "")
        if not ref:
            continue
        asset_var = str(
            asset.get("variable")
            or (next(iter(mapped_vars.keys())) if len(mapped_vars) == 1 else "")
        )
        if asset_var:
            raster_refs[asset_var] = ref

    embedded_series: dict[str, ObservationSeries] = {}
    raw_ts_map = extensions.get("time_series")
    if isinstance(raw_ts_map, Mapping):
        has_catalog_ts_vars = catalog_spec is not None and any(
            _resolve_catalog_var(str(k), catalog_spec) is not None for k in raw_ts_map
        )
        for var_name, ts_payload in raw_ts_map.items():
            if not isinstance(ts_payload, Mapping):
                continue
            var_name_str = str(var_name)
            canonical_alias = _CANONICAL_ALIAS_MAP.get(var_name_str)
            if (
                has_catalog_ts_vars
                and _resolve_catalog_var(var_name_str, catalog_spec) is None
                and var_name_str != "accumulated_depth_mm"
            ):
                continue
            var_meta = (
                mapped_vars.get(var_name_str)
                or (mapped_vars.get(canonical_alias) if canonical_alias else None)
                or _resolve_catalog_var(var_name_str, catalog_spec)
            )
            if var_meta is None and var_name_str == "accumulated_depth_mm":
                var_meta = VariableMetadata(
                    name="accumulated_depth_mm",
                    canonical_name="precipitation_depth",
                    units=str(ts_payload.get("units") or "mm"),
                    semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
                    is_scaled=True,
                )
            if var_meta is None:
                continue
            if var_meta.semantic_kind in {
                VariableSemanticKind.QA_FLAG,
                VariableSemanticKind.COORDINATE,
            }:
                continue
            target_key = canonical_alias or var_name_str
            var_updates: dict[str, Any] = {"name": target_key}
            if "is_scaled" in ts_payload:
                var_updates["is_scaled"] = bool(ts_payload["is_scaled"])
            ts_units = ts_payload.get("units")
            if isinstance(ts_units, str) and ts_units.strip():
                var_updates["units"] = ts_units.strip()
            var_meta = var_meta.model_copy(update=var_updates)
            mapped_vars[target_key] = var_meta
            ts_dates = [_parse_datetime(x) for x in ts_payload.get("timestamps", [])]
            vals = [_optional_float(v) for v in ts_payload.get("values", [])]
            qa_raw = dict(ts_payload.get("qa_layers") or {})
            qa_layers: dict[str, list[int | None]] = {}
            for k, q_vals in qa_raw.items():
                key = str(k)
                if not isinstance(q_vals, list):
                    continue
                if key == "precipitationQualityIndex":
                    qa_layers["pqi_milli"] = [
                        None if (qf := _optional_float(q)) is None else round(qf * 1000)
                        for q in q_vals
                    ]
                else:
                    qa_layers[key] = [
                        None if (qf := _optional_float(q)) is None else round(qf) for q in q_vals
                    ]
            series_obj = ObservationSeries(
                timestamps=ts_dates,
                values=vals,
                qa_layers=qa_layers,
                overpass_tags=ts_payload.get("overpass_tags"),
                metadata=var_meta,
            )
            embedded_series[target_key] = series_obj

    granule_raw = payload.get("granule_id")
    granule_ids = (str(granule_raw),) if granule_raw else ()

    retrieval_raw = provenance.get("retrieval_timestamp")
    retrieval_ts = _parse_datetime(retrieval_raw) if retrieval_raw else None

    overpass_raw = extensions.get("overpass_mode")
    overpass_mode = OverpassMode(overpass_raw) if isinstance(overpass_raw, str) else None

    dataset_id = str(payload.get("dataset_id") or "")
    if not dataset_id:
        raise ScientificInputError("GHS dataset payload must include dataset_id")

    limitations = list(catalog_spec.limitations) if catalog_spec else []
    processing_steps = provenance.get("processing_steps")
    prov_notes = [f"GHS step: {step}" for step in processing_steps] if processing_steps else []

    return ScientificDataset(
        dataset_id=dataset_id,
        source_id=source_id,
        product=product or (catalog_spec.product if catalog_spec else "custom"),
        product_version=str(
            payload.get("product_version")
            or (catalog_spec.product_version if catalog_spec else "1.0")
        ),
        provider=provider or (catalog_spec.provider if catalog_spec else "ghs"),
        run_type=str(extensions["run_type"]) if "run_type" in extensions else None,
        overpass_mode=overpass_mode,
        granule_ids=granule_ids,
        retrieval_timestamp=retrieval_ts,
        spatial_support=spatial_support,
        temporal_metadata=temporal_meta,
        variables=mapped_vars,
        series=embedded_series,
        raster_refs=raster_refs,
        ghs_dataset_id=dataset_id,
        provenance_notes=prov_notes,
        limitations=limitations,
    )


class LocalArtifactDatasetLoader:
    """Safe local JSON/NPZ/GeoTIFF loader implementing DatasetLoaderPort."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir.resolve() if base_dir is not None else None

    def _resolve_path(self, ref: str) -> Path:
        raw_path = Path(ref)
        if raw_path.is_absolute():
            candidate = raw_path.resolve()
        elif self._base_dir is not None:
            candidate = (self._base_dir / raw_path).resolve()
        else:
            candidate = raw_path.resolve()
        if self._base_dir is not None and not candidate.is_relative_to(self._base_dir):
            raise ScientificInputError(
                f"Artifact reference escapes configured base directory: {ref}",
                code="unsafe_artifact_path",
            )
        if not candidate.exists():
            raise ScientificInputError(
                f"Dataset artifact file does not exist: {candidate}",
                code="missing_artifact",
            )
        return candidate

    def load_dataset(self, dataset_ref: str) -> ScientificDataset:
        """Load JSON manifest matching either ScientificDataset or GHS DatasetOut contract."""
        path = self._resolve_path(dataset_ref)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ScientificInputError(f"Manifest must be a JSON object: {path}")
        if "spatial_support" in payload and "temporal_metadata" in payload:
            return ScientificDataset.model_validate(payload)
        return map_ghs_dataset_payload(payload)

    def load_grid_stack(
        self,
        dataset: ScientificDataset,
        variable_name: str,
    ) -> ScientificGridStack | None:
        """Load 3D numpy array artifact (.npz/.npy) or GeoTIFF if geospatial extra is available."""
        ref = dataset.raster_refs.get(variable_name)
        if ref is None:
            return None
        var_meta = dataset.variables.get(variable_name)
        if var_meta is None:
            raise ScientificInputError(f"Unknown variable '{variable_name}' in dataset")
        path = self._resolve_path(ref)
        suffix = path.suffix.lower()

        if suffix == ".npz":
            with np.load(path, allow_pickle=False) as archive:
                if "data" not in archive:
                    raise ScientificInputError(f"NPZ archive missing 'data' array: {path}")
                data = np.asarray(archive["data"], dtype=np.float64)
                qa_arrays: dict[str, NDArray[np.int64]] = {
                    k: np.asarray(archive[k], dtype=np.int64)
                    for k in archive.files
                    if k not in {"data", "timestamps", "cell_areas_m2", "aoi_mask"}
                }
                cell_areas = (
                    np.asarray(archive["cell_areas_m2"], dtype=np.float64)
                    if "cell_areas_m2" in archive.files
                    else None
                )
                aoi_mask = (
                    np.asarray(archive["aoi_mask"], dtype=bool)
                    if "aoi_mask" in archive.files
                    else None
                )
            series = dataset.series.get(variable_name)
            timestamps = (
                list(series.timestamps)
                if series is not None and len(series.timestamps) == data.shape[0]
                else [dataset.temporal_metadata.start for _ in range(data.shape[0])]
            )
            return ScientificGridStack(
                dataset_id=dataset.dataset_id,
                source_id=dataset.source_id,
                product=dataset.product,
                product_version=dataset.product_version,
                variable=var_meta,
                spatial_support=dataset.spatial_support,
                timestamps=timestamps,
                data=data,
                qa_arrays=qa_arrays,
                cell_areas_m2=cell_areas,
                aoi_mask=aoi_mask,
            )

        if suffix in {".tif", ".tiff"}:
            return self._load_geotiff_stack(path, dataset, var_meta)

        raise ScientificInputError(f"Unsupported local grid format '{suffix}' for {path}")

    def _load_geotiff_stack(
        self,
        path: Path,
        dataset: ScientificDataset,
        var_meta: VariableMetadata,
    ) -> ScientificGridStack:
        try:
            import rasterio
        except ImportError as exc:
            raise ScientificInputError(
                "Reading GeoTIFF grid artifacts requires the 'terra-scientific[geospatial]' "
                "optional dependency.",
                code="missing_geospatial_extra",
            ) from exc

        with rasterio.open(path) as src:
            arr = src.read().astype(np.float64)
            if src.nodata is not None:
                arr = np.where(arr == float(src.nodata), np.nan, arr)
        series = dataset.series.get(var_meta.name)
        timestamps = (
            list(series.timestamps)
            if series is not None and len(series.timestamps) == arr.shape[0]
            else [dataset.temporal_metadata.start for _ in range(arr.shape[0])]
        )
        return ScientificGridStack(
            dataset_id=dataset.dataset_id,
            source_id=dataset.source_id,
            product=dataset.product,
            product_version=dataset.product_version,
            variable=var_meta,
            spatial_support=dataset.spatial_support,
            timestamps=timestamps,
            data=arr,
        )
