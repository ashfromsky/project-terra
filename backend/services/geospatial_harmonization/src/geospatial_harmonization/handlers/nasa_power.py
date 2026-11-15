"""NASA POWER handler preserving MERRA-2 vs. CERES native variable provenance."""

import json
import math
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import (
    ProviderDisabledError,
    ProviderResponseError,
    ProviderValidationError,
)
from geospatial_harmonization.domain.models.dataset import (
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSemantics,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import SpatialBounds
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.handlers.base import (
    build_provenance,
    build_time_series_extension,
    parse_handler_payload,
    safe_fetch_bytes,
    validate_wgs84_bbox,
    write_raw_asset,
)
from geospatial_harmonization.handlers.catalog import DiscoveryResult

# tuple: (daily_unit, hourly_unit, native_res_deg, source_product, semantics)
_POWER_META: dict[str, tuple[str, str, str, str, VariableSemantics]] = {
    "T2M": ("degC", "degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "T2M_MAX": ("degC", "degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "T2M_MIN": ("degC", "degC", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "RH2M": ("%", "%", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "WS10M": ("m/s", "m/s", "0.5x0.625", "MERRA-2", "continuous_intensive"),
    "PRECTOTCORR": ("mm/day", "mm/hour", "0.5x0.625", "MERRA-2", "continuous_extensive"),
    "ALLSKY_SFC_SW_DWN": (
        "MJ/m^2/day",
        "MJ/hr",
        "1.0x1.0",
        "CERES SYN1deg",
        "continuous_intensive",
    ),
    "CLRSKY_SFC_SW_DWN": (
        "MJ/m^2/day",
        "MJ/hr",
        "1.0x1.0",
        "CERES SYN1deg",
        "continuous_intensive",
    ),
}
_MIN_REGIONAL_SPAN_DEG = 2.0


def _as_map(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _parse_power_timestamp(key: str, temporal: Literal["daily", "hourly"]) -> datetime | None:
    fmt = "%Y%m%d%H" if temporal == "hourly" else "%Y%m%d"
    if len(key) != (10 if temporal == "hourly" else 8):
        return None
    try:
        return datetime.strptime(key, fmt).replace(tzinfo=UTC)
    except ValueError:
        return None


def _is_valid_power_timestamp(key: str, temporal: Literal["daily", "hourly"]) -> bool:
    return _parse_power_timestamp(key, temporal) is not None


class NASAPowerPayload(BaseModel):
    """Validated query parameters for NASA POWER point, regional, or auto retrieval."""

    model_config = ConfigDict(extra="forbid")

    product: str = "nasa_power"
    mode: Literal["point", "regional", "auto"] = "point"
    temporal: Literal["daily", "hourly"] = "daily"
    community: str = "AG"
    parameters: tuple[str, ...]
    start_date: date | None = None
    end_date: date | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    bbox: tuple[float, float, float, float] | None = None
    latitude: float | None = None
    longitude: float | None = None
    min_lat: float | None = None
    max_lat: float | None = None
    min_lon: float | None = None
    max_lon: float | None = None

    @model_validator(mode="after")
    def _validate_request(self) -> "NASAPowerPayload":
        if not self.parameters:
            raise ValueError("parameters must be non-empty")

        if self.start_date is None and self.start_time is not None:
            dt0 = (
                self.start_time.replace(tzinfo=UTC)
                if self.start_time.tzinfo is None
                else self.start_time.astimezone(UTC)
            )
            self.start_date = dt0.date()
        if self.end_date is None and self.end_time is not None:
            dt1 = (
                self.end_time.replace(tzinfo=UTC)
                if self.end_time.tzinfo is None
                else self.end_time.astimezone(UTC)
            )
            self.end_date = dt1.date()
        if self.start_date is None or self.end_date is None:
            raise ValueError("start_date and end_date (or start_time and end_time) are required")
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")

        if self.bbox is not None:
            validate_wgs84_bbox(self.bbox)

        if self.mode == "auto":
            if self.bbox is not None:
                min_lon, min_lat, max_lon, max_lat = self.bbox
                if (max_lon - min_lon) >= _MIN_REGIONAL_SPAN_DEG and (
                    max_lat - min_lat
                ) >= _MIN_REGIONAL_SPAN_DEG:
                    self.mode = "regional"
                    self.min_lon = min_lon if self.min_lon is None else self.min_lon
                    self.min_lat = min_lat if self.min_lat is None else self.min_lat
                    self.max_lon = max_lon if self.max_lon is None else self.max_lon
                    self.max_lat = max_lat if self.max_lat is None else self.max_lat
                else:
                    self.mode = "point"
                    if self.longitude is None:
                        self.longitude = (min_lon + max_lon) / 2.0
                    if self.latitude is None:
                        self.latitude = (min_lat + max_lat) / 2.0
            elif self.latitude is not None and self.longitude is not None:
                self.mode = "point"
            elif all(
                v is not None for v in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)
            ):
                self.mode = "regional"
            else:
                raise ValueError("auto mode requires bbox, point coordinates, or regional bounds")

        if self.mode == "point":
            if self.bbox is not None and (self.latitude is None or self.longitude is None):
                self.longitude = (self.bbox[0] + self.bbox[2]) / 2.0
                self.latitude = (self.bbox[1] + self.bbox[3]) / 2.0
            if self.latitude is None or self.longitude is None:
                raise ValueError("point mode requires latitude and longitude")
            if not (-90.0 <= self.latitude <= 90.0) or not (-180.0 <= self.longitude <= 180.0):
                raise ValueError("point latitude/longitude out of bounds")
        else:
            if self.bbox is not None and any(
                v is None for v in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)
            ):
                min_lon, min_lat, max_lon, max_lat = self.bbox
                self.min_lon = min_lon if self.min_lon is None else self.min_lon
                self.min_lat = min_lat if self.min_lat is None else self.min_lat
                self.max_lon = max_lon if self.max_lon is None else self.max_lon
                self.max_lat = max_lat if self.max_lat is None else self.max_lat
            if any(v is None for v in (self.min_lat, self.max_lat, self.min_lon, self.max_lon)):
                raise ValueError("regional mode requires min_lat, max_lat, min_lon, and max_lon")
            min_lat = float(self.min_lat)  # type: ignore[arg-type]
            max_lat = float(self.max_lat)  # type: ignore[arg-type]
            min_lon = float(self.min_lon)  # type: ignore[arg-type]
            max_lon = float(self.max_lon)  # type: ignore[arg-type]
            if max_lat <= min_lat or max_lon <= min_lon:
                raise ValueError("regional bbox max coordinates must exceed min coordinates")
            if (max_lat - min_lat) < _MIN_REGIONAL_SPAN_DEG or (
                max_lon - min_lon
            ) < _MIN_REGIONAL_SPAN_DEG:
                raise ValueError(
                    "NASA POWER regional mode requires at least a 2.0 degree lat/lon span; "
                    "use mode='point' for smaller areas"
                )
        return self


class NASAPowerHandler:
    """DataHandler for NASA POWER agro-climatology point and regional REST APIs."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        raw_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self._base_url = cfg.nasa_power_base_url.rstrip("/")
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._backoff_seconds = cfg.http_retry_backoff_seconds
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "nasa_power"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("nasa_power", "power_daily", "power_hourly")

    async def discover(
        self,
        *,
        product: str,
        bbox: tuple[float, float, float, float],
        start_time: datetime,
        end_time: datetime,
        limit: int = 10,
    ) -> tuple[DiscoveryResult, ...]:
        """Validate AOI and temporal bounds against documented NASA POWER availability."""
        del limit
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "NASA POWER provider is disabled by configuration (NASA_POWER_ENABLED=false)",
                provider=self.provider,
            )
        if end_time < start_time:
            raise ProviderValidationError(
                "end_time cannot precede start_time", provider=self.provider
            )
        validate_wgs84_bbox(bbox)
        temporal = "hourly" if product == "power_hourly" else "daily"
        earliest_year = 2001 if temporal == "hourly" else 1981
        if end_time.year < earliest_year:
            raise ProviderValidationError(
                f"NASA POWER {temporal} archive begins in {earliest_year}",
                provider=self.provider,
            )
        lon_span = bbox[2] - bbox[0]
        lat_span = bbox[3] - bbox[1]
        query_mode = (
            "regional"
            if (lon_span >= _MIN_REGIONAL_SPAN_DEG and lat_span >= _MIN_REGIONAL_SPAN_DEG)
            else "point"
        )
        return (
            DiscoveryResult(
                observation_id=f"nasa_power_{temporal}_{start_time:%Y%m%d}_{end_time:%Y%m%d}",
                provider=self.provider,
                product=product,
                product_version="v2",
                title=f"NASA POWER {temporal} continuous archive ({query_mode} query eligible)",
                time_start=start_time,
                time_end=end_time,
                bbox=bbox,
                query_mode=query_mode,
                access_hint=f"{self._base_url}/api/temporal/{temporal}/{query_mode}",
                metadata={
                    "auth_required": False,
                    "temporal": temporal,
                    "regional_min_span_deg": _MIN_REGIONAL_SPAN_DEG,
                },
            ),
        )

    def _build_query(
        self, req: NASAPowerPayload, params_override: tuple[str, ...] | None = None
    ) -> tuple[str, dict[str, str]]:
        start_d = req.start_date
        end_d = req.end_date
        assert start_d is not None and end_d is not None
        chosen_params = params_override or req.parameters
        url = f"{self._base_url}/temporal/{req.temporal}/{req.mode}"
        params = {
            "parameters": ",".join(chosen_params),
            "community": req.community,
            "start": start_d.strftime("%Y%m%d"),
            "end": end_d.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        if req.mode == "point":
            params["latitude"] = str(req.latitude)
            params["longitude"] = str(req.longitude)
        else:
            params["latitude-min"] = str(req.min_lat)
            params["latitude-max"] = str(req.max_lat)
            params["longitude-min"] = str(req.min_lon)
            params["longitude-max"] = str(req.max_lon)
        return url, params

    async def _fetch_power_doc(
        self, url: str, params: dict[str, str]
    ) -> tuple[bytes, dict[str, object], str, str]:
        host = (urlparse(self._base_url).hostname or "").lower()
        raw, final_url, media = await safe_fetch_bytes(
            url,
            allowed_hosts=[host] if host else None,
            params=params,
            timeout=self._timeout,
            max_retries=self._max_retries,
            backoff_seconds=self._backoff_seconds,
            transport=self._transport,
            require_https=True,
            earthdata_auth=False,
        )
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError(f"Invalid NASA POWER JSON response: {exc}") from exc
        if not isinstance(doc, Mapping):
            raise ProviderResponseError("NASA POWER response root must be a JSON object")
        return raw, dict(doc), final_url, media

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch NASA POWER JSON publicly (no Earthdata auth), validate values, and harmonize."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "NASA POWER provider is disabled by configuration (NASA_POWER_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(NASAPowerPayload, payload)

        param_batches = (
            tuple((p,) for p in req.parameters)
            if req.mode == "regional" and len(req.parameters) > 1
            else (req.parameters,)
        )

        docs: list[dict[str, object]] = []
        raw_blobs: list[bytes] = []
        source_urls: list[str] = []
        last_media = "application/json"
        for batch in param_batches:
            url, params = self._build_query(req, params_override=batch)
            raw_part, doc_part, final_url, media = await self._fetch_power_doc(url, params)
            raw_blobs.append(raw_part)
            docs.append(doc_part)
            source_urls.append(final_url)
            if media:
                last_media = media

        merged_doc = _merge_power_docs(docs) if len(docs) > 1 else docs[0]
        raw_payload = (
            raw_blobs[0]
            if len(raw_blobs) == 1
            else json.dumps(merged_doc, separators=(",", ":")).encode("utf-8")
        )

        start_d = req.start_date
        end_d = req.end_date
        assert start_d is not None and end_d is not None

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_power_"))
        fname = f"power_{req.mode}_{req.temporal}_{start_d:%Y%m%d}_{end_d:%Y%m%d}.json"
        _, asset = write_raw_asset(base_dir, fname, raw_payload, "json", last_media)

        header = _as_map(merged_doc.get("header"))
        raw_fill = header.get("fill_value")
        fill_val = float(raw_fill) if isinstance(raw_fill, (int, float)) else -999.0
        param_meta = _as_map(merged_doc.get("parameters"))
        raw_feats = merged_doc.get("features")
        features_raw: list[object] = raw_feats if isinstance(raw_feats, list) else [merged_doc]
        if req.mode == "regional" and isinstance(raw_feats, list) and not raw_feats:
            raise ProviderResponseError("NASA POWER regional response contained zero features")

        total_obs = 0
        fill_count = 0
        null_count = 0
        invalid_ts_count = 0
        sample_coords: list[list[float]] = []
        param_ts_buckets: dict[str, dict[str, list[float]]] = {p: {} for p in req.parameters}
        param_ts_keys: dict[str, dict[str, datetime]] = {p: {} for p in req.parameters}

        for feat in features_raw:
            fmap = _as_map(feat)
            geom = _as_map(fmap.get("geometry"))
            coords = geom.get("coordinates")
            if (
                isinstance(coords, list)
                and len(coords) >= 2
                and all(isinstance(c, (int, float)) for c in coords[:2])
            ):
                sample_coords.append([float(c) for c in coords])
            props = _as_map(fmap.get("properties"))
            param_map = _as_map(props.get("parameter"))
            for p_raw, series in param_map.items():
                if not isinstance(series, Mapping):
                    continue
                p_key = str(p_raw)
                for ts_key, val in series.items():
                    ts_str = str(ts_key)
                    total_obs += 1
                    parsed_dt = _parse_power_timestamp(ts_str, req.temporal)
                    if parsed_dt is None:
                        invalid_ts_count += 1
                        continue
                    if p_key in param_ts_keys:
                        param_ts_keys[p_key][ts_str] = parsed_dt
                    if val is None:
                        null_count += 1
                    elif isinstance(val, (int, float)):
                        fval = float(val)
                        if not math.isfinite(fval) or math.isclose(fval, fill_val):
                            fill_count += 1
                        elif p_key in param_ts_buckets:
                            param_ts_buckets[p_key].setdefault(ts_str, []).append(fval)
                    else:
                        null_count += 1

        excluded = fill_count + null_count + invalid_ts_count
        exclusion_breakdown = {
            name: count
            for name, count in (
                ("fill_nodata", fill_count),
                ("missing_null", null_count),
                ("invalid_timestamp", invalid_ts_count),
            )
            if count > 0
        }

        variables: dict[str, VariableSpec] = {}
        dims = ("time",) if req.mode == "point" else ("point", "time")
        resolutions_seen: set[str] = set()
        for p_name in req.parameters:
            daily_unit, hourly_unit, native_res, src_prod, semantics = _POWER_META.get(
                p_name, ("1", "1", "unknown", "NASA POWER", "continuous_intensive")
            )
            if native_res != "unknown":
                resolutions_seen.add(f"{native_res} deg {src_prod}")
            default_unit = hourly_unit if req.temporal == "hourly" else daily_unit
            api_info = _as_map(param_meta.get(p_name))
            raw_unit = api_info.get("units")
            unit = raw_unit if isinstance(raw_unit, str) and raw_unit.strip() else default_unit
            attrs: dict[str, object] = {
                "native_resolution_deg": native_res,
                "source_product": src_prod,
                "temporal_resolution": req.temporal,
            }
            if p_name == "PRECTOTCORR" and req.temporal == "hourly":
                attrs["supports_rate_to_depth"] = True
                attrs["interval_duration_hours"] = 1.0
            variables[p_name] = VariableSpec(
                name=p_name,
                units=unit,
                dtype="float32",
                dimensions=dims,
                semantics=semantics,
                nodata=fill_val,
                attributes=attrs,
            )

        t_start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=UTC)
        t_end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=UTC) + timedelta(days=1)
        valid_frac = (total_obs - excluded) / total_obs if total_obs > 0 else None
        missing_frac = excluded / total_obs if total_obs > 0 else None
        bounds = (
            SpatialBounds(*req.bbox)
            if req.bbox is not None
            else (
                None
                if req.mode == "point"
                else SpatialBounds(
                    float(req.min_lon or 0.0),
                    float(req.min_lat or 0.0),
                    float(req.max_lon or 0.0),
                    float(req.max_lat or 0.0),
                )
            )
        )
        spatial = SpatialMetadata(
            representation="point" if req.mode == "point" else "grid_series",
            crs="EPSG:4326",
            bounds=bounds,
            point_count=1 if req.mode == "point" else len(features_raw),
            spatial_resolution="; ".join(sorted(resolutions_seen)) or "0.5x0.625 deg MERRA-2",
        )
        api_ver = str(_as_map(header.get("api")).get("version", "v2"))
        source_id = f"nasa_power_{req.mode}_{req.temporal}_{start_d:%Y%m%d}_{end_d:%Y%m%d}"
        cadence = "1h" if req.temporal == "hourly" else "daily"

        time_series_ext: dict[str, object] = {}
        total_feat_count = max(1, len(features_raw))
        max_ts_count = 0
        max_valid_ts = 0
        for p_name, var_spec in variables.items():
            ts_dt_map = param_ts_keys.get(p_name, {})
            if not ts_dt_map:
                continue
            ordered_items = sorted(ts_dt_map.items(), key=lambda pair: pair[1])
            ts_dts = [dt for _, dt in ordered_items]
            vals: list[float | None] = []
            valid_counts: list[int] = []
            total_counts: list[int] = []
            for ts_str, _ in ordered_items:
                bucket = param_ts_buckets[p_name].get(ts_str, [])
                if bucket:
                    vals.append(sum(bucket) / len(bucket))
                    valid_counts.append(len(bucket))
                else:
                    vals.append(None)
                    valid_counts.append(0)
                total_counts.append(total_feat_count)
            max_ts_count = max(max_ts_count, len(ts_dts))
            max_valid_ts = max(max_valid_ts, sum(1 for v in vals if v is not None))
            time_series_ext[p_name] = build_time_series_extension(
                timestamps=ts_dts,
                values=vals,
                units=var_spec.units,
                valid_pixel_counts=valid_counts,
                total_pixel_counts=total_counts,
            )
        prov = build_provenance(
            self.provider,
            req.product,
            api_ver,
            source_urls[0],
            granule_id=source_id,
            source_metadata={
                "community": req.community,
                "temporal": req.temporal,
                "header": dict(header),
                "sources": header.get("sources"),
                "batched_requests": len(source_urls),
            },
        )
        if len(source_urls) > 1:
            prov = build_provenance(
                self.provider,
                req.product,
                api_ver,
                source_urls[0],
                granule_id=source_id,
                source_metadata={**prov.source_metadata, "all_source_urls": source_urls},
            )

        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=source_id,
            provider=self.provider,
            product=req.product,
            product_version=api_ver,
            granule_id=source_id,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=spatial,
            temporal_metadata=TemporalSpec(t_start, t_end, cadence, "interval"),
            quality_metadata=QualityMetadata(
                qa_policy="nasa_power_fill_and_null_exclusion",
                valid_observation_fraction=valid_frac,
                missing_data_fraction=missing_frac,
                excluded_count=excluded,
                exclusion_reasons=tuple(sorted(exclusion_breakdown)),
                exclusion_breakdown=exclusion_breakdown,
            ),
            assets=(asset,),
            provenance=prov,
            extensions={
                "point_count": spatial.point_count,
                "mode": req.mode,
                "temporal": req.temporal,
                "coordinates_preview": sample_coords[:5],
                "time_series": time_series_ext,
                "ingestion_summary": {
                    "mode": req.mode,
                    "temporal": req.temporal,
                    "parameters": list(req.parameters),
                    "requested_count": 1,
                    "succeeded_count": 1,
                    "failed_count": 0,
                    "partial_failures": [],
                    "valid_timestamps": max_valid_ts,
                    "total_timestamps": max_ts_count,
                },
            },
        )


def _merge_power_docs(docs: list[dict[str, object]]) -> dict[str, object]:
    """Merge single-parameter NASA POWER regional GeoJSON responses by point coordinate."""
    base = dict(docs[0])
    merged_params: dict[str, object] = dict(_as_map(base.get("parameters")))
    feat_by_coord: dict[tuple[float, ...], dict[str, object]] = {}

    for doc in docs:
        merged_params.update(_as_map(doc.get("parameters")))
        raw_feats = doc.get("features")
        if not isinstance(raw_feats, list):
            continue
        for idx, raw_feat in enumerate(raw_feats):
            fmap = dict(_as_map(raw_feat))
            geom = _as_map(fmap.get("geometry"))
            coords = geom.get("coordinates")
            coord_key = (
                tuple(round(float(c), 6) for c in coords[:2])
                if isinstance(coords, list) and len(coords) >= 2
                else (float(idx),)
            )
            props = dict(_as_map(fmap.get("properties")))
            param_series = dict(_as_map(props.get("parameter")))
            existing = feat_by_coord.get(coord_key)
            if existing is None:
                feat_by_coord[coord_key] = {
                    "type": fmap.get("type", "Feature"),
                    "geometry": dict(geom),
                    "properties": {**props, "parameter": param_series},
                }
            else:
                ex_props = existing["properties"]
                assert isinstance(ex_props, dict)
                ex_param = ex_props["parameter"]
                assert isinstance(ex_param, dict)
                ex_param.update(param_series)

    base["parameters"] = merged_params
    base["features"] = list(feat_by_coord.values())
    return base
