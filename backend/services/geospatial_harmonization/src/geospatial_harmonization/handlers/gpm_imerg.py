"""GPM IMERG half-hourly precipitation handler (V06/V07, Early/Late/Final)."""

import asyncio
import math
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import (
    ProviderDisabledError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.handlers.base import (
    CmrGranule,
    build_provenance,
    build_time_series_extension,
    discover_cmr_granules,
    discover_cmr_observations,
    earthdata_hosts_for,
    extract_aoi_mask_for_decoded,
    gather_bounded_granules,
    parse_handler_payload,
    safe_fetch_to_file,
    select_representative_granules,
    validate_wgs84_bbox,
)
from geospatial_harmonization.handlers.catalog import DiscoveryResult
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.transformations.temporal import (
    TemporalAggregationResult,
    integrate_rate_to_depth,
)

IMERGProduct = Literal["GPM_3IMERGHH.07", "GPM_3IMERGHH.06", "GPM_3IMERGHHE.07", "GPM_3IMERGHHL.07"]
RunType = Literal["Early", "Late", "Final"]

_MAX_IMERG_RATE_MM_HR = 2000.0

_RUN_MAP: dict[str, RunType] = {
    "GPM_3IMERGHHE.07": "Early",
    "GPM_3IMERGHHL.07": "Late",
    "GPM_3IMERGHH.07": "Final",
    "GPM_3IMERGHH.06": "Final",
}


class GPMIMERGPayload(BaseModel):
    """Input schema for GPM IMERG half-hourly precipitation granule ingestion."""

    model_config = ConfigDict(extra="forbid")

    product: IMERGProduct = "GPM_3IMERGHH.07"
    granule_url: str | None = None
    granule_urls: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    end_time: datetime | None = None
    max_granules: int = Field(default=12, ge=1, le=256)
    max_concurrency: int = Field(default=3, ge=1, le=8)
    run_type: RunType | None = None
    data_format: DataFormat = "netcdf"
    variables: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "GPMIMERGPayload":
        if self.bbox is not None:
            validate_wgs84_bbox(self.bbox)
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot precede start_time")
        return self


@dataclass(frozen=True, slots=True)
class _ImergGranuleOutcome:
    url: str
    final_url: str
    asset: AssetReference
    decoded: DecodedDataset
    variables: dict[str, VariableSpec]
    precip_key: str
    pqi_key: str | None
    liq_key: str | None
    run_type: RunType
    granule_id: str
    temporal: TemporalSpec
    sanitized_aoi_rate: np.ndarray
    rate_mean: float | None
    interval_depth_mean_mm: float | None
    low_pqi_count: int
    mean_liquid_pct: float | None
    mean_pqi: float | None
    valid_count: int
    excluded_count: int
    total_count: int
    excluded_breakdown: dict[str, int]
    aoi_valid_px: int
    aoi_total_px: int
    src_meta: dict[str, object]


def _parse_imerg_start_attr(attrs: Mapping[str, object]) -> datetime | None:
    raw = attrs.get("StartGranuleDateTime")
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _infer_run_type(product: str, url: str, explicit: RunType | None) -> RunType:
    if explicit is not None:
        return explicit
    upper = url.upper()
    if "3B-HHR-E" in upper or "HHE" in product:
        return "Early"
    if "3B-HHR-L" in upper or "HHL" in product:
        return "Late"
    return _RUN_MAP.get(product, "Final")


def _detect_imerg_format(path: Path, default_format: DataFormat) -> DataFormat:
    suffix = path.suffix.lower()
    if suffix in (".h5", ".hdf5", ".he5"):
        return "hdf5"
    if suffix in (".nc", ".nc4"):
        return "netcdf"
    return default_format


def accumulate_imerg_rates(
    rate_arrays: list[np.ndarray],
    windows: list[TemporalSpec],
    *,
    min_coverage_fraction: float = 0.5,
    nodata: float | int | None = -9999.9,
) -> TemporalAggregationResult:
    """Integrate contiguous half-hourly IMERG rate arrays (mm/hr) into total depth (mm)."""
    if not rate_arrays or len(rate_arrays) != len(windows):
        raise QualityPolicyViolationError(
            "rate_arrays and windows must be non-empty and match length"
        )
    ordered = sorted(zip(windows, rate_arrays, strict=True), key=lambda pair: pair[0].start)
    target = TemporalSpec(
        start=ordered[0][0].start,
        end=ordered[-1][0].end,
        cadence=f"{len(ordered) * 30}min",
        semantics="interval",
        aggregation="rate_to_depth_sum",
    )
    return integrate_rate_to_depth(
        [arr for _, arr in ordered],
        [win for win, _ in ordered],
        target,
        min_coverage_fraction=min_coverage_fraction,
        nodata=nodata,
    )


class GPMIMERGHandler:
    """DataHandler for GPM IMERG V06/V07 preserving interval rate & run provenance."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        reader_registry: ReaderRegistry | None = None,
        raw_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self._cmr_url = cfg.cmr_base_url.rstrip("/")
        self._token = cfg.earthdata_token.get_secret_value() if cfg.earthdata_token else None
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._backoff_seconds = cfg.http_retry_backoff_seconds
        self._presigned_hosts = tuple(cfg.earthdata_presigned_hosts)
        self._max_object_bytes = min(cfg.ghs_storage_max_object_bytes, cfg.http_max_download_bytes)
        self._chunk_bytes = cfg.ghs_storage_stream_chunk_bytes
        self._readers = reader_registry or build_default_reader_registry()
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "gpm_imerg"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("GPM_3IMERGHH.07", "GPM_3IMERGHH.06", "GPM_3IMERGHHE.07", "GPM_3IMERGHHL.07")

    async def discover(
        self,
        *,
        product: str,
        bbox: tuple[float, float, float, float],
        start_time: datetime,
        end_time: datetime,
        limit: int = 10,
    ) -> tuple[DiscoveryResult, ...]:
        """Discover GPM IMERG granules from NASA CMR for an AOI and time window."""
        return await discover_cmr_observations(
            enabled=self._settings.is_provider_enabled(self.provider),
            provider=self.provider,
            product=product,
            cmr_url=self._cmr_url,
            token=self._token,
            extensions=(".hdf5", ".h5", ".nc4", ".nc"),
            bbox=bbox,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            timeout=self._timeout,
            max_retries=self._max_retries,
            backoff_seconds=self._backoff_seconds,
            transport=self._transport,
        )

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch IMERG half-hour granule batch, validate rate units/QA, and accumulate depth."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "GPM IMERG provider is disabled by configuration (GPM_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(GPMIMERGPayload, payload)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)

        explicit_urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_u in [*([req.granule_url] if req.granule_url else []), *req.granule_urls]:
            if raw_u and raw_u not in seen_urls:
                seen_urls.add(raw_u)
                explicit_urls.append(raw_u)

        targets: list[tuple[int, str, CmrGranule | None]] = []
        selection_meta: dict[str, Any] = {
            "discovered_count": len(explicit_urls),
            "selection_strategy": "explicit_urls",
        }
        if explicit_urls:
            for idx, target_url in enumerate(explicit_urls[: req.max_granules]):
                targets.append((idx, target_url, None))
        else:
            t1 = (
                req.end_time.astimezone(UTC)
                if req.end_time is not None
                else t0 + timedelta(minutes=30)
            )
            granules = await discover_cmr_granules(
                self._cmr_url,
                req.product,
                t0,
                t1,
                (".hdf5", ".h5", ".nc4", ".nc"),
                bbox=req.bbox,
                headers=None,
                page_size=min(max(req.max_granules * 4, 200), 2000),
                max_pages=5,
                stratify_target=req.max_granules,
                timeout=self._timeout,
                max_retries=self._max_retries,
                backoff_seconds=self._backoff_seconds,
                transport=self._transport,
                require_https=True,
            )
            ordered_granules, selection_meta = select_representative_granules(
                granules, req.max_granules, window_start=t0
            )
            targets = [(idx, g.data_url, g) for idx, g in enumerate(ordered_granules)]

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_imerg_"))
        is_batch = len(targets) > 1

        async def _ingest_one(item: tuple[int, str, CmrGranule | None]) -> _ImergGranuleOutcome:
            idx, url, cmr_granule = item
            base_pref = (
                cmr_granule.producer_granule_id
                if cmr_granule
                and cmr_granule.producer_granule_id.lower().endswith(
                    (".hdf5", ".h5", ".nc4", ".nc")
                )
                else Path(urlparse(url).path).name or f"{req.product}.HDF5"
            )
            preferred_name = f"{idx:03d}_{base_pref}" if is_batch else base_pref
            initial_fmt = _detect_imerg_format(Path(base_pref), req.data_format)
            path, asset, final_url = await safe_fetch_to_file(
                url,
                base_dir,
                filename=preferred_name,
                fallback_filename=f"{req.product}.HDF5",
                data_format=initial_fmt,
                allowed_hosts=earthdata_hosts_for(self._cmr_url),
                presigned_hosts=self._presigned_hosts,
                headers=headers,
                timeout=self._timeout,
                max_retries=self._max_retries,
                backoff_seconds=self._backoff_seconds,
                transport=self._transport,
                require_https=True,
                earthdata_auth=True,
                max_bytes=self._max_object_bytes,
                chunk_bytes=self._chunk_bytes,
            )
            actual_fmt = _detect_imerg_format(path, asset.data_format)
            if actual_fmt != asset.data_format:
                asset = replace(asset, data_format=actual_fmt)

            fname = path.name
            decoded = await asyncio.to_thread(
                self._readers.read, asset, path, variables=req.variables
            )

            preferred = ("precipitation", "precipitationCal")
            precip_key = next(
                (
                    k
                    for target in preferred
                    for k in decoded.variables
                    if k.rsplit("/", 1)[-1] == target
                ),
                next(iter(decoded.variables)),
            )
            variables: dict[str, VariableSpec] = {}
            for name, spec in decoded.variables.items():
                leaf = name.rsplit("/", 1)[-1]
                if leaf in ("precipitation", "precipitationCal"):
                    raw_units = spec.units.strip()
                    if raw_units.lower() in ("mm", "mm/day", "mm/30min", "mm/30m"):
                        raise QualityPolicyViolationError(
                            f"IMERG half-hourly '{leaf}' must represent precipitation rate "
                            f"(mm/hr), got incompatible units '{spec.units}'"
                        )
                    norm_units = "mm/hr" if raw_units in ("1", "mm/h") else spec.units
                    variables[name] = replace(
                        spec,
                        units=norm_units,
                        semantics="continuous_extensive",
                        valid_range=(0.0, _MAX_IMERG_RATE_MM_HR),
                        attributes={
                            **spec.attributes,
                            "interval_duration_hours": 0.5,
                            "supports_rate_to_depth": True,
                        },
                    )
                elif leaf == "precipitationQualityIndex":
                    variables[name] = replace(spec, units="1" if spec.units == "1" else spec.units)
                else:
                    variables[name] = spec

            win_start = (
                cmr_granule.time_start
                if cmr_granule and cmr_granule.time_start
                else (
                    _parse_imerg_start_attr(decoded.attributes)
                    or (t0 + timedelta(minutes=30 * idx))
                )
            )
            win_end = (
                cmr_granule.time_end
                if cmr_granule and cmr_granule.time_end and cmr_granule.time_end > win_start
                else win_start + timedelta(minutes=30)
            )
            temporal = TemporalSpec(
                win_start,
                win_end,
                "30min",
                "interval",
                aggregation="rate_to_depth_sum",
                acquisition_timestamp=win_start,
            )

            precip_spec = variables[precip_key]
            p_arr = np.asarray(decoded.arrays[precip_key], dtype=np.float64)
            if p_arr.size == 0:
                raise QualityPolicyViolationError(
                    f"IMERG variable '{precip_key}' contains zero elements"
                )

            fill_mask = ~np.isfinite(p_arr)
            if precip_spec.nodata is not None:
                fill_mask |= p_arr == float(precip_spec.nodata)
            out_of_range = (~fill_mask) & ((p_arr < 0.0) | (p_arr > _MAX_IMERG_RATE_MM_HR))

            pqi_key = next(
                (k for k in variables if k.rsplit("/", 1)[-1] == "precipitationQualityIndex"),
                None,
            )
            pqi_arr: np.ndarray | None = None
            pqi_invalid = np.zeros_like(fill_mask, dtype=bool)
            low_pqi_count = 0
            if pqi_key is not None:
                pqi_raw = np.asarray(decoded.arrays[pqi_key], dtype=np.float64)
                pqi_spec = variables[pqi_key]
                if pqi_raw.shape == p_arr.shape:
                    pqi_arr = pqi_raw
                    pqi_invalid = ~np.isfinite(pqi_arr) | (pqi_arr < 0.0)
                    if pqi_spec.nodata is not None:
                        pqi_invalid |= pqi_arr == float(pqi_spec.nodata)
                    low_pqi_count = int(np.count_nonzero((~pqi_invalid) & (pqi_arr < 0.2)))

            invalid_mask = fill_mask | out_of_range | pqi_invalid
            sanitized_rate = np.where(invalid_mask, np.nan, p_arr)
            depth_res = integrate_rate_to_depth(
                [sanitized_rate], [temporal], temporal, nodata=np.nan
            )

            excluded_breakdown = {
                name: count
                for name, mask in (
                    ("fill_nodata", fill_mask),
                    ("out_of_range", out_of_range),
                    ("invalid_pqi", pqi_invalid),
                )
                if (count := int(np.count_nonzero(mask))) > 0
            }
            excluded = int(np.count_nonzero(invalid_mask))
            valid_count = int(p_arr.size - excluded)

            aoi_mask: np.ndarray | None = None
            if p_arr.ndim >= 2:
                aoi_mask = extract_aoi_mask_for_decoded(
                    decoded,
                    (p_arr.shape[-2], p_arr.shape[-1]),
                    req.bbox,
                    dims=precip_spec.dimensions,
                )
            broad_aoi: np.ndarray | None = (
                np.broadcast_to(aoi_mask, p_arr.shape)
                if aoi_mask is not None and p_arr.ndim >= 2
                else None
            )
            if broad_aoi is not None:
                aoi_valid = (~invalid_mask) & broad_aoi
                aoi_total_px = int(np.count_nonzero(broad_aoi))
            else:
                aoi_valid = ~invalid_mask
                aoi_total_px = int(p_arr.size)
            aoi_valid_px = int(np.count_nonzero(aoi_valid))
            rate_mean = float(np.mean(p_arr[aoi_valid])) if aoi_valid_px > 0 else None
            sanitized_aoi = np.where(aoi_valid, p_arr, np.nan)

            mean_pqi: float | None = None
            if pqi_arr is not None:
                if aoi_valid_px > 0:
                    pqi_aoi = aoi_valid
                elif broad_aoi is not None:
                    pqi_aoi = (~pqi_invalid) & broad_aoi
                else:
                    pqi_aoi = ~pqi_invalid
                if np.any(pqi_aoi):
                    mean_pqi = float(np.mean(pqi_arr[pqi_aoi]))

            liq_key = next(
                (k for k in variables if k.rsplit("/", 1)[-1] == "probabilityLiquidPrecipitation"),
                None,
            )
            mean_liquid_pct: float | None = None
            if liq_key is not None:
                liq_arr = np.asarray(decoded.arrays[liq_key], dtype=np.float64)
                liq_spec = variables[liq_key]
                liq_valid = np.isfinite(liq_arr) & (liq_arr >= 0.0) & (liq_arr <= 100.0)
                if liq_spec.nodata is not None:
                    liq_valid &= liq_arr != float(liq_spec.nodata)
                if np.any(liq_valid):
                    mean_liquid_pct = float(np.mean(liq_arr[liq_valid]))

            run_type = _infer_run_type(req.product, final_url, req.run_type)
            granule_id = (
                (cmr_granule.producer_granule_id if cmr_granule else None)
                or str(decoded.attributes.get("GranuleID") or "").strip()
                or fname
            )
            src_meta: dict[str, object] = {}
            if cmr_granule is not None:
                src_meta["cmr"] = dict(cmr_granule.source_metadata)
            for attr_key in (
                "DOI",
                "ShortName",
                "VersionID",
                "StartGranuleDateTime",
                "StopGranuleDateTime",
            ):
                if attr_key in decoded.attributes:
                    src_meta[attr_key] = decoded.attributes[attr_key]

            mean_depth = (
                float(np.nanmean(depth_res.data)) if depth_res.valid_pixels > 0 else math.nan
            )
            return _ImergGranuleOutcome(
                url=url,
                final_url=final_url,
                asset=asset,
                decoded=decoded,
                variables=variables,
                precip_key=precip_key,
                pqi_key=pqi_key,
                liq_key=liq_key,
                run_type=run_type,
                granule_id=granule_id,
                temporal=temporal,
                sanitized_aoi_rate=sanitized_aoi,
                rate_mean=rate_mean,
                interval_depth_mean_mm=None if math.isnan(mean_depth) else mean_depth,
                low_pqi_count=low_pqi_count,
                mean_liquid_pct=mean_liquid_pct,
                mean_pqi=mean_pqi,
                valid_count=valid_count,
                excluded_count=excluded,
                total_count=int(p_arr.size),
                excluded_breakdown=excluded_breakdown,
                aoi_valid_px=aoi_valid_px,
                aoi_total_px=aoi_total_px,
                src_meta=src_meta,
            )

        outcomes, partial_failures = await gather_bounded_granules(
            targets,
            _ingest_one,
            max_items=req.max_granules,
            max_concurrency=req.max_concurrency,
            key_fn=lambda row: row[1],
        )
        outcomes.sort(key=lambda item: (item.temporal.start, item.granule_id))

        run_types_seen = {item.run_type for item in outcomes}
        if len(run_types_seen) > 1:
            raise QualityPolicyViolationError(
                f"Mixed IMERG run types detected ({sorted(run_types_seen)}); "
                "cannot silently combine Early/Late/Final runs"
            )

        first = outcomes[0]
        ver = req.product.split(".", 1)[1]
        min_start = min(item.temporal.start for item in outcomes)
        max_end = max(item.temporal.end for item in outcomes)
        overall_temporal = (
            first.temporal
            if len(outcomes) == 1
            else TemporalSpec(
                min_start,
                max_end,
                "30min",
                "interval",
                aggregation="rate_to_depth_sum",
                acquisition_timestamp=first.temporal.start,
            )
        )

        if len(outcomes) == 1:
            accum_depth_mm = first.interval_depth_mean_mm
        else:
            shapes = {item.sanitized_aoi_rate.shape for item in outcomes}
            if len(shapes) == 1:
                accum_res = integrate_rate_to_depth(
                    [item.sanitized_aoi_rate for item in outcomes],
                    [item.temporal for item in outcomes],
                    overall_temporal,
                    min_coverage_fraction=0.0,
                    nodata=np.nan,
                )
                accum_depth_mm = (
                    float(np.nanmean(accum_res.data)) if accum_res.valid_pixels > 0 else None
                )
            else:
                depth_vals = [
                    item.interval_depth_mean_mm
                    for item in outcomes
                    if item.interval_depth_mean_mm is not None
                ]
                accum_depth_mm = sum(depth_vals) if depth_vals else None

        total_px_all = sum(item.total_count for item in outcomes)
        excluded_all = sum(item.excluded_count for item in outcomes)
        valid_all = sum(item.valid_count for item in outcomes)
        agg_breakdown: dict[str, int] = {}
        for item in outcomes:
            for key_name, cnt in item.excluded_breakdown.items():
                agg_breakdown[key_name] = agg_breakdown.get(key_name, 0) + cnt
        valid_frac = (valid_all / total_px_all) if total_px_all > 0 else 0.0
        missing_frac = (excluded_all / total_px_all) if total_px_all > 0 else 1.0

        ts_list: list[datetime] = []
        val_list: list[float | None] = []
        pqi_list: list[int | float | None] = []
        valid_px_list: list[int] = []
        total_px_list: list[int] = []
        for item in outcomes:
            ts_list.append(item.temporal.start)
            val_list.append(item.rate_mean)
            pqi_list.append(item.mean_pqi)
            valid_px_list.append(item.aoi_valid_px)
            total_px_list.append(item.aoi_total_px)

        qa_layers_ext: dict[str, list[int | float | None]] = {}
        if any(p is not None for p in pqi_list):
            qa_layers_ext["precipitationQualityIndex"] = pqi_list

        time_series_ext: dict[str, Any] = {
            first.precip_key: build_time_series_extension(
                timestamps=ts_list,
                values=val_list,
                units=first.variables[first.precip_key].units,
                qa_layers=qa_layers_ext,
                valid_pixel_counts=valid_px_list,
                total_pixel_counts=total_px_list,
                is_scaled=True,
            )
        }

        liq_vals = [item.mean_liquid_pct for item in outcomes if item.mean_liquid_pct is not None]
        agg_liquid_pct = (sum(liq_vals) / len(liq_vals)) if liq_vals else None
        agg_granule_id = (
            first.granule_id if len(outcomes) == 1 else f"{first.granule_id}+{len(outcomes) - 1}"
        )
        agg_source_id = (
            (first.asset.checksum_sha256 or Path(first.url).name)
            if len(outcomes) == 1
            else f"{req.product}_{min_start:%Y%m%d%H%M}_{max_end:%Y%m%d%H%M}_{len(outcomes)}"
        )
        prov_meta = dict(first.src_meta)
        if len(outcomes) > 1:
            prov_meta["granule_ids"] = [item.granule_id for item in outcomes]
            prov_meta["all_source_urls"] = [item.final_url for item in outcomes]

        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=agg_source_id,
            provider=self.provider,
            product=req.product,
            product_version=ver,
            granule_id=agg_granule_id,
            variables=first.variables,
            units={k: v.units for k, v in first.variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                first.decoded.crs or "EPSG:4326",
                first.decoded.grid.bounds if first.decoded.grid else None,
                first.decoded.grid,
                spatial_resolution="0.1 deg (~10 km)",
            ),
            temporal_metadata=overall_temporal,
            quality_metadata=QualityMetadata(
                qa_policy="imerg_interval_coverage",
                valid_observation_fraction=valid_frac,
                missing_data_fraction=missing_frac,
                excluded_count=excluded_all,
                exclusion_reasons=tuple(sorted(agg_breakdown)),
                exclusion_breakdown=agg_breakdown,
                flags_applied=tuple(k for k in (first.pqi_key, first.liq_key) if k is not None),
            ),
            assets=tuple(item.asset for item in outcomes),
            provenance=build_provenance(
                self.provider,
                req.product,
                ver,
                first.final_url,
                run_type=first.run_type,
                granule_id=agg_granule_id,
                source_metadata=prov_meta,
            ),
            extensions={
                "precip_variable": first.precip_key,
                "run_type": first.run_type,
                "interval_depth_mean_mm": first.interval_depth_mean_mm,
                "accumulated_depth_mm": accum_depth_mm,
                "low_pqi_pixel_count": sum(item.low_pqi_count for item in outcomes),
                "mean_liquid_precip_probability_pct": agg_liquid_pct,
                "time_series": time_series_ext,
                "ingestion_summary": {
                    "product": req.product,
                    "run_type": first.run_type,
                    "requested_count": len(targets),
                    "succeeded_count": len(outcomes),
                    "failed_count": len(partial_failures),
                    "partial_failures": partial_failures,
                    "granule_ids": [item.granule_id for item in outcomes],
                    "bbox_applied": list(req.bbox) if req.bbox is not None else None,
                    **selection_meta,
                },
            },
        )
