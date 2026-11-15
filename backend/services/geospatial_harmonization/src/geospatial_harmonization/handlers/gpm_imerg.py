"""GPM IMERG half-hourly precipitation handler (V06/V07, Early/Late/Final)."""

import math
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import (
    ProviderDisabledError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.dataset import (
    DataFormat,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.handlers.base import (
    CmrGranule,
    build_provenance,
    discover_cmr_granules,
    discover_cmr_observations,
    earthdata_hosts_for,
    parse_handler_payload,
    safe_fetch_to_file,
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
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    run_type: RunType | None = None
    data_format: DataFormat = "netcdf"
    variables: tuple[str, ...] | None = None


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
        """Fetch IMERG half-hour granule, validate rate units/QA, and record depth summary."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "GPM IMERG provider is disabled by configuration (GPM_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(GPMIMERGPayload, payload)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)
        t1 = t0 + timedelta(minutes=30)

        cmr_granule: CmrGranule | None = None
        if req.granule_url:
            url = req.granule_url
        else:
            granules = await discover_cmr_granules(
                self._cmr_url,
                req.product,
                t0,
                t1,
                (".hdf5", ".h5", ".nc4", ".nc"),
                bbox=req.bbox,
                headers=None,
                page_size=5,
                timeout=self._timeout,
                max_retries=self._max_retries,
                backoff_seconds=self._backoff_seconds,
                transport=self._transport,
                require_https=True,
            )
            cmr_granule = granules[0]
            url = cmr_granule.data_url

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_imerg_"))
        preferred_name = (
            cmr_granule.producer_granule_id
            if cmr_granule
            and cmr_granule.producer_granule_id.lower().endswith((".hdf5", ".h5", ".nc4", ".nc"))
            else Path(urlparse(url).path).name or f"{req.product}.HDF5"
        )
        initial_fmt = _detect_imerg_format(Path(preferred_name), req.data_format)
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
        decoded = self._readers.read(asset, path, variables=req.variables)

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
                        f"IMERG half-hourly '{leaf}' must represent precipitation rate (mm/hr), "
                        f"got incompatible units '{spec.units}'"
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

        win_start = cmr_granule.time_start if cmr_granule and cmr_granule.time_start else t0
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
        pqi_invalid = np.zeros_like(fill_mask, dtype=bool)
        low_pqi_count = 0
        if pqi_key is not None:
            pqi_arr = np.asarray(decoded.arrays[pqi_key], dtype=np.float64)
            pqi_spec = variables[pqi_key]
            if pqi_arr.shape == p_arr.shape:
                pqi_invalid = ~np.isfinite(pqi_arr) | (pqi_arr < 0.0)
                if pqi_spec.nodata is not None:
                    pqi_invalid |= pqi_arr == float(pqi_spec.nodata)
                low_pqi_count = int(np.count_nonzero((~pqi_invalid) & (pqi_arr < 0.2)))

        invalid_mask = fill_mask | out_of_range | pqi_invalid
        sanitized_rate = np.where(invalid_mask, np.nan, p_arr)
        depth_res = integrate_rate_to_depth([sanitized_rate], [temporal], temporal, nodata=np.nan)

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
        valid_frac = valid_count / p_arr.size
        missing_frac = excluded / p_arr.size

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
        ver = req.product.split(".", 1)[1]
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

        mean_depth = float(np.nanmean(depth_res.data)) if depth_res.valid_pixels > 0 else math.nan
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=asset.checksum_sha256 or fname,
            provider=self.provider,
            product=req.product,
            product_version=ver,
            granule_id=granule_id,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                decoded.crs or "EPSG:4326",
                decoded.grid.bounds if decoded.grid else None,
                decoded.grid,
                spatial_resolution="0.1 deg (~10 km)",
            ),
            temporal_metadata=temporal,
            quality_metadata=QualityMetadata(
                qa_policy="imerg_interval_coverage",
                valid_observation_fraction=valid_frac,
                missing_data_fraction=missing_frac,
                excluded_count=excluded,
                exclusion_reasons=tuple(sorted(excluded_breakdown)),
                exclusion_breakdown=excluded_breakdown,
                flags_applied=tuple(k for k in (pqi_key, liq_key) if k is not None),
            ),
            assets=(asset,),
            provenance=build_provenance(
                self.provider,
                req.product,
                ver,
                final_url,
                run_type=run_type,
                granule_id=granule_id,
                source_metadata=src_meta,
            ),
            extensions={
                "precip_variable": precip_key,
                "run_type": run_type,
                "interval_depth_mean_mm": None if math.isnan(mean_depth) else mean_depth,
                "low_pqi_pixel_count": low_pqi_count,
                "mean_liquid_precip_probability_pct": mean_liquid_pct,
            },
        )
