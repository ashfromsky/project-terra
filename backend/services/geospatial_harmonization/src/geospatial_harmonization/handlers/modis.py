"""MODIS handler (MOD13Q1.061, MOD11A2.061) with Sinusoidal CRS and bitmask QA screening."""

import asyncio
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
from pyproj import CRS

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
from geospatial_harmonization.storage.scratch import run_with_owned_base_dir

MODIS_SINUSOIDAL_WKT = CRS.from_proj4(
    "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
).to_wkt()

_PRODUCT_RESOLUTION: dict[str, str] = {
    "MOD13Q1.061": "250 m",
    "MOD11A2.061": "1 km",
}

_PRODUCT_SPECS: dict[str, tuple[int, str, dict[str, VariableSpec]]] = {
    "MOD13Q1.061": (
        16,
        "16daily",
        {
            "250m 16 days NDVI": VariableSpec(
                "250m 16 days NDVI",
                "1",
                "int16",
                ("y", "x"),
                "continuous_intensive",
                nodata=-3000,
                scale_factor=0.0001,
                valid_range=(-0.2, 1.0),
            ),
            "250m 16 days EVI": VariableSpec(
                "250m 16 days EVI",
                "1",
                "int16",
                ("y", "x"),
                "continuous_intensive",
                nodata=-3000,
                scale_factor=0.0001,
                valid_range=(-0.2, 1.0),
            ),
            "250m 16 days VI Quality": VariableSpec(
                "250m 16 days VI Quality", "bitmask", "uint16", ("y", "x"), "qa_flag"
            ),
            "250m 16 days pixel reliability": VariableSpec(
                "250m 16 days pixel reliability", "code", "int8", ("y", "x"), "qa_flag", nodata=-1
            ),
        },
    ),
    "MOD11A2.061": (
        8,
        "8daily",
        {
            "LST_Day_1km": VariableSpec(
                "LST_Day_1km",
                "K",
                "uint16",
                ("y", "x"),
                "continuous_intensive",
                nodata=0,
                scale_factor=0.02,
                valid_range=(150.0, 380.0),
            ),
            "LST_Night_1km": VariableSpec(
                "LST_Night_1km",
                "K",
                "uint16",
                ("y", "x"),
                "continuous_intensive",
                nodata=0,
                scale_factor=0.02,
                valid_range=(150.0, 380.0),
            ),
            "QC_Day": VariableSpec("QC_Day", "bitmask", "uint8", ("y", "x"), "qa_flag"),
            "QC_Night": VariableSpec("QC_Night", "bitmask", "uint8", ("y", "x"), "qa_flag"),
        },
    ),
}


@dataclass(frozen=True, slots=True)
class ModisQaEvaluation:
    """Pixel-level MODIS quality evaluation summary without mutating raw arrays."""

    valid_mask: np.ndarray
    valid_fraction: float
    missing_fraction: float
    excluded_count: int
    exclusion_breakdown: dict[str, int]
    reasons: tuple[str, ...]


def decode_mod13q1_pixel_reliability(reliability: np.ndarray) -> dict[str, np.ndarray]:
    """Decode MOD13Q1 pixel reliability codes (-1 fill, 0 good, 1 marginal, 2 snow/ice, 3 cloud)."""
    arr = np.asarray(reliability, dtype=np.int16)
    return {
        "qa_fill": arr == -1,
        "good": arr == 0,
        "marginal": arr == 1,
        "snow_ice": arr == 2,
        "cloudy": arr == 3,
        "qa_unrecognized": (arr < -1) | (arr > 3),
    }


def decode_mod13q1_vi_quality(vi_quality: np.ndarray) -> dict[str, np.ndarray]:
    """Decode MOD13Q1 Collection 6.1 16-bit VI Quality bitmask (LSB bit 0)."""
    qa = np.asarray(vi_quality, dtype=np.uint16)
    modland = qa & np.uint16(0x03)
    usefulness = (qa >> np.uint16(2)) & np.uint16(0x0F)
    adj_cloud = ((qa >> np.uint16(8)) & np.uint16(0x01)) == 1
    mixed_cloud = ((qa >> np.uint16(10)) & np.uint16(0x01)) == 1
    snow_ice = ((qa >> np.uint16(14)) & np.uint16(0x01)) == 1
    shadow = ((qa >> np.uint16(15)) & np.uint16(0x01)) == 1
    return {
        "cloudy": (modland == 2) | adj_cloud | mixed_cloud,
        "not_produced": modland == 3,
        "snow_ice": snow_ice,
        "shadow": shadow,
        "low_usefulness": usefulness >= 14,
        "marginal_modland": modland == 1,
    }


def decode_mod11a2_qc(qc: np.ndarray) -> dict[str, np.ndarray]:
    """Decode MOD11A2 Collection 6.1 8-bit QC_Day/QC_Night Mandatory QA flags."""
    arr = np.asarray(qc, dtype=np.uint8)
    mandatory = arr & np.uint8(0x03)
    lst_error = (arr >> np.uint8(6)) & np.uint8(0x03)
    return {
        "cloudy": mandatory == 2,
        "not_produced": mandatory == 3,
        "marginal_modland": mandatory == 1,
        "high_lst_error": (mandatory <= 1) & (lst_error == 3),
    }


_MODIS_CANONICAL_NAMES: dict[str, str] = {
    "250m 16 days NDVI": "NDVI",
    "250m 16 days EVI": "EVI",
    "LST_Day_1km": "LST_Day_1km",
    "LST_Night_1km": "LST_Night_1km",
}


def _evaluate_variable_masks(
    product: str,
    primary: VariableSpec,
    arrays: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    raw = np.asarray(arrays[primary.name])
    if raw.size == 0:
        raise QualityPolicyViolationError(f"MODIS variable '{primary.name}' contains zero elements")

    fill_mask = (
        (raw == primary.nodata) if primary.nodata is not None else np.zeros_like(raw, dtype=bool)
    )
    raw_f = raw.astype(np.float64, copy=False)
    fill_mask = fill_mask | ~np.isfinite(raw_f)
    scale = primary.scale_factor if primary.scale_factor is not None else 1.0
    offset = primary.add_offset if primary.add_offset is not None else 0.0
    physical = raw_f * scale + offset

    out_of_range = np.zeros_like(fill_mask, dtype=bool)
    if primary.valid_range is not None:
        lo, hi = primary.valid_range
        out_of_range = (~fill_mask) & ((physical < lo) | (physical > hi))

    reasons_masks: dict[str, np.ndarray] = {
        "fill_nodata": fill_mask,
        "out_of_range": out_of_range,
    }

    if product == "MOD13Q1.061":
        if "250m 16 days pixel reliability" in arrays:
            pr = np.asarray(arrays["250m 16 days pixel reliability"])
            if pr.shape != raw.shape:
                raise QualityPolicyViolationError("MOD13Q1 pixel reliability shape mismatch")
            decoded_pr = decode_mod13q1_pixel_reliability(pr)
            for key in ("qa_fill", "snow_ice", "cloudy", "qa_unrecognized"):
                reasons_masks[key] = decoded_pr[key]
        if "250m 16 days VI Quality" in arrays:
            vi_q = np.asarray(arrays["250m 16 days VI Quality"])
            if vi_q.shape != raw.shape:
                raise QualityPolicyViolationError("MOD13Q1 VI Quality shape mismatch")
            decoded_vi = decode_mod13q1_vi_quality(vi_q)
            for key in ("cloudy", "not_produced", "snow_ice", "shadow", "low_usefulness"):
                prev = reasons_masks.get(key)
                reasons_masks[key] = (
                    (prev | decoded_vi[key]) if prev is not None else decoded_vi[key]
                )
    elif product == "MOD11A2.061":
        qc_key = (
            "QC_Night" if primary.name == "LST_Night_1km" and "QC_Night" in arrays else "QC_Day"
        )
        if qc_key in arrays:
            qc = np.asarray(arrays[qc_key])
            if qc.shape != raw.shape:
                raise QualityPolicyViolationError(f"MOD11A2 {qc_key} shape mismatch")
            decoded_qc = decode_mod11a2_qc(qc)
            for key in ("cloudy", "not_produced", "high_lst_error"):
                reasons_masks[key] = decoded_qc[key]

    excluded = np.zeros_like(fill_mask, dtype=bool)
    for mask in reasons_masks.values():
        excluded |= mask
    return physical, ~excluded, reasons_masks


def evaluate_modis_quality(
    product: str,
    variables: Mapping[str, VariableSpec],
    arrays: Mapping[str, object],
) -> ModisQaEvaluation:
    """Evaluate MODIS fill, physical bounds, and QA bitmasks across primary scientific variables."""
    primary_specs = [
        spec for spec in variables.values() if spec.semantics not in ("qa_flag", "categorical")
    ]
    if not primary_specs:
        return ModisQaEvaluation(
            valid_mask=np.zeros(0, dtype=bool),
            valid_fraction=0.0,
            missing_fraction=1.0,
            excluded_count=0,
            exclusion_breakdown={},
            reasons=("no_continuous_scientific_variable",),
        )

    primary = primary_specs[0]
    _, valid_mask, reasons_masks = _evaluate_variable_masks(product, primary, arrays)
    excluded = ~valid_mask

    breakdown = {
        reason: count
        for reason, mask in reasons_masks.items()
        if (count := int(np.count_nonzero(mask))) > 0
    }
    excluded_count = int(np.count_nonzero(excluded))
    valid_count = int(np.count_nonzero(valid_mask))
    total = int(valid_mask.size)
    valid_frac = valid_count / total
    missing_frac = excluded_count / total
    reasons = tuple(sorted(breakdown))
    if valid_count == 0:
        reasons = (*reasons, "all_pixels_rejected_by_qa_or_fill")

    return ModisQaEvaluation(
        valid_mask=valid_mask,
        valid_fraction=valid_frac,
        missing_fraction=missing_frac,
        excluded_count=excluded_count,
        exclusion_breakdown=breakdown,
        reasons=reasons,
    )


def _representative_qa_code(
    qa_arr: np.ndarray,
    eff_mask: np.ndarray,
    aoi_mask: np.ndarray | None,
) -> int | None:
    if qa_arr.shape != eff_mask.shape:
        return None
    if np.any(eff_mask):
        sample = qa_arr[eff_mask]
    elif aoi_mask is not None and np.any(aoi_mask):
        sample = qa_arr[aoi_mask]
    else:
        sample = qa_arr.ravel()
    if sample.size == 0:
        return None
    vals, counts = np.unique(sample, return_counts=True)
    return int(vals[int(np.argmax(counts))])


def _parse_hdf_date(attrs: Mapping[str, object]) -> datetime | None:
    raw = attrs.get("RANGEBEGINNINGDATE")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class _ModisVarObs:
    canonical_name: str
    units: str
    timestamp: datetime
    value: float | None
    valid_pixels: int
    total_pixels: int
    qa_values: dict[str, int | None]


@dataclass(frozen=True, slots=True)
class _ModisGranuleOutcome:
    url: str
    final_url: str
    asset: AssetReference
    decoded: DecodedDataset
    variables: dict[str, VariableSpec]
    qa_eval: ModisQaEvaluation
    granule_id: str
    win_start: datetime
    win_end: datetime
    src_meta: dict[str, object]
    observations: tuple[_ModisVarObs, ...]


class MODISPayload(BaseModel):
    """Input schema for MODIS product granule ingestion."""

    model_config = ConfigDict(extra="forbid")

    product: Literal["MOD13Q1.061", "MOD11A2.061"]
    granule_url: str | None = None
    granule_urls: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    end_time: datetime | None = None
    max_granules: int = Field(default=12, ge=1, le=256)
    max_concurrency: int = Field(default=3, ge=1, le=8)
    data_format: DataFormat = "hdf4"
    variables: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "MODISPayload":
        if self.bbox is not None:
            validate_wgs84_bbox(self.bbox)
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot precede start_time")
        return self


class MODISHandler:
    """DataHandler for MODIS vegetation (MOD13Q1) and LST (MOD11A2) products."""

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
        return "modis"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("MOD13Q1.061", "MOD11A2.061")

    async def discover(
        self,
        *,
        product: str,
        bbox: tuple[float, float, float, float],
        start_time: datetime,
        end_time: datetime,
        limit: int = 10,
    ) -> tuple[DiscoveryResult, ...]:
        """Discover MODIS granules from NASA CMR for an AOI and time window."""
        return await discover_cmr_observations(
            enabled=self._settings.is_provider_enabled(self.provider),
            provider=self.provider,
            product=product,
            cmr_url=self._cmr_url,
            token=self._token,
            extensions=(".hdf", ".tif", ".tiff"),
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
        """Download MODIS granule batch via CMR/Earthdata, apply QA screening, and build dataset."""
        return await run_with_owned_base_dir(
            lambda base_dir: self._handle_payload(payload, base_dir),
            settings=self._settings,
            prefix="ghs_modis_",
            raw_dir=self._raw_dir,
        )

    async def _handle_payload(
        self, payload: Mapping[str, object], base_dir: Path
    ) -> SpatialDataset:
        """Download MODIS granules into ``base_dir``, apply QA screening, build dataset."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "MODIS provider is disabled by configuration (MODIS_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(MODISPayload, payload)
        comp_days, cadence, template_specs = _PRODUCT_SPECS[req.product]
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
                else t0 + timedelta(days=comp_days)
            )
            granules = await discover_cmr_granules(
                self._cmr_url,
                req.product,
                t0,
                t1,
                (".hdf", ".tif", ".tiff"),
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

        is_batch = len(targets) > 1

        async def _ingest_one(item: tuple[int, str, CmrGranule | None]) -> _ModisGranuleOutcome:
            idx, url, cmr_granule = item
            base_pref = (
                cmr_granule.producer_granule_id
                if cmr_granule
                and cmr_granule.producer_granule_id.endswith((".hdf", ".tif", ".tiff"))
                else Path(urlparse(url).path).name or f"{req.product}.hdf"
            )
            preferred_name = f"{idx:03d}_{base_pref}" if is_batch else base_pref
            path, asset, final_url = await safe_fetch_to_file(
                url,
                base_dir,
                filename=preferred_name,
                fallback_filename=f"{req.product}.hdf",
                data_format=req.data_format,
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
            fname = path.name
            decoded = await asyncio.to_thread(
                self._readers.read, asset, path, variables=req.variables
            )

            decoded_vars = decoded.variables
            if (
                req.variables is None
                and template_specs
                and any(name in template_specs for name in decoded_vars)
            ):
                decoded_vars = {
                    name: spec for name, spec in decoded_vars.items() if name in template_specs
                }

            variables: dict[str, VariableSpec] = {}
            for name, dec_spec in decoded_vars.items():
                known = template_specs.get(name)
                if known is None:
                    variables[name] = dec_spec
                else:
                    variables[name] = replace(
                        known,
                        dimensions=dec_spec.dimensions,
                        dtype=dec_spec.dtype,
                        nodata=dec_spec.nodata if dec_spec.nodata is not None else known.nodata,
                        grid=dec_spec.grid,
                    )

            qa_eval = evaluate_modis_quality(req.product, variables, decoded.arrays)
            local_granule_id = str(decoded.attributes.get("LOCALGRANULEID") or "").strip()
            granule_id = (
                (cmr_granule.producer_granule_id if cmr_granule else None)
                or local_granule_id
                or fname
            )

            win_start = (
                cmr_granule.time_start
                if cmr_granule and cmr_granule.time_start
                else (_parse_hdf_date(decoded.attributes) or (t0 + timedelta(days=idx * comp_days)))
            )
            win_end = (
                cmr_granule.time_end
                if cmr_granule and cmr_granule.time_end and cmr_granule.time_end > win_start
                else win_start + timedelta(days=comp_days)
            )

            src_meta: dict[str, object] = {}
            if cmr_granule is not None:
                src_meta["cmr"] = dict(cmr_granule.source_metadata)
            for key in (
                "LOCALGRANULEID",
                "SHORTNAME",
                "VERSIONID",
                "RANGEBEGINNINGDATE",
                "RANGEENDINGDATE",
            ):
                if key in decoded.attributes:
                    src_meta[key] = decoded.attributes[key]

            obs_list: list[_ModisVarObs] = []
            for spec in variables.values():
                if spec.semantics in ("qa_flag", "categorical", "coordinate"):
                    continue
                if spec.name not in decoded.arrays:
                    continue
                phys, var_valid, _ = _evaluate_variable_masks(req.product, spec, decoded.arrays)
                aoi_mask: np.ndarray | None = None
                if phys.ndim >= 2:
                    aoi_mask = extract_aoi_mask_for_decoded(
                        decoded, (phys.shape[-2], phys.shape[-1]), req.bbox
                    )
                if aoi_mask is not None and phys.ndim == 2:
                    eff_mask = var_valid & aoi_mask
                    total_px = int(np.count_nonzero(aoi_mask))
                else:
                    eff_mask = var_valid
                    total_px = int(var_valid.size)
                valid_px = int(np.count_nonzero(eff_mask))
                mean_val = float(np.mean(phys[eff_mask])) if valid_px > 0 else None

                qa_values: dict[str, int | None] = {}
                if req.product == "MOD13Q1.061":
                    if "250m 16 days pixel reliability" in decoded.arrays:
                        qa_values["pixel_reliability"] = _representative_qa_code(
                            np.asarray(decoded.arrays["250m 16 days pixel reliability"]),
                            eff_mask,
                            aoi_mask,
                        )
                    if "250m 16 days VI Quality" in decoded.arrays:
                        qa_values["vi_quality"] = _representative_qa_code(
                            np.asarray(decoded.arrays["250m 16 days VI Quality"]),
                            eff_mask,
                            aoi_mask,
                        )
                elif req.product == "MOD11A2.061":
                    qc_key = (
                        "QC_Night"
                        if spec.name == "LST_Night_1km" and "QC_Night" in decoded.arrays
                        else "QC_Day"
                    )
                    if qc_key in decoded.arrays:
                        qa_values[qc_key] = _representative_qa_code(
                            np.asarray(decoded.arrays[qc_key]),
                            eff_mask,
                            aoi_mask,
                        )

                canon = _MODIS_CANONICAL_NAMES.get(spec.name, spec.name)
                obs_list.append(
                    _ModisVarObs(
                        canonical_name=canon,
                        units=spec.units,
                        timestamp=win_start,
                        value=mean_val,
                        valid_pixels=valid_px,
                        total_pixels=total_px,
                        qa_values=qa_values,
                    )
                )

            return _ModisGranuleOutcome(
                url=url,
                final_url=final_url,
                asset=asset,
                decoded=decoded,
                variables=variables,
                qa_eval=qa_eval,
                granule_id=granule_id,
                win_start=win_start,
                win_end=win_end,
                src_meta=src_meta,
                observations=tuple(obs_list),
            )

        outcomes, partial_failures = await gather_bounded_granules(
            targets,
            _ingest_one,
            max_items=req.max_granules,
            max_concurrency=req.max_concurrency,
            key_fn=lambda row: row[1],
        )
        outcomes.sort(key=lambda item: (item.win_start, item.granule_id))

        first = outcomes[0]
        all_assets = tuple(item.asset for item in outcomes)
        min_start = min(item.win_start for item in outcomes)
        max_end = max(item.win_end for item in outcomes)
        temporal = TemporalSpec(
            min_start,
            max_end,
            cadence,
            "composite",
            composite_days=comp_days,
            acquisition_timestamp=first.win_start,
        )

        if len(outcomes) == 1:
            qa_meta = QualityMetadata(
                "modis_qa_bitmask_screened",
                valid_observation_fraction=first.qa_eval.valid_fraction,
                missing_data_fraction=first.qa_eval.missing_fraction,
                excluded_count=first.qa_eval.excluded_count,
                exclusion_reasons=first.qa_eval.reasons,
                exclusion_breakdown=first.qa_eval.exclusion_breakdown,
                flags_applied=tuple(
                    k for k, v in first.variables.items() if v.semantics == "qa_flag"
                ),
            )
            agg_granule_id = first.granule_id
            agg_source_id = first.asset.checksum_sha256 or Path(first.url).name
            unreliable_all = first.qa_eval.valid_fraction == 0.0
        else:
            agg_breakdown: dict[str, int] = {}
            total_px_all = 0
            total_valid_all = 0
            total_excluded_all = 0
            reason_set: set[str] = set()
            for item in outcomes:
                ev = item.qa_eval
                px_item = int(ev.valid_mask.size)
                total_px_all += px_item
                total_excluded_all += ev.excluded_count
                total_valid_all += max(0, px_item - ev.excluded_count)
                for r_name, r_cnt in ev.exclusion_breakdown.items():
                    agg_breakdown[r_name] = agg_breakdown.get(r_name, 0) + r_cnt
                reason_set.update(ev.reasons)
            valid_frac_all = (total_valid_all / total_px_all) if total_px_all > 0 else 0.0
            missing_frac_all = (total_excluded_all / total_px_all) if total_px_all > 0 else 1.0
            if total_valid_all == 0:
                reason_set.add("all_pixels_rejected_by_qa_or_fill")
            qa_meta = QualityMetadata(
                "modis_qa_bitmask_screened",
                valid_observation_fraction=valid_frac_all,
                missing_data_fraction=missing_frac_all,
                excluded_count=total_excluded_all,
                exclusion_reasons=tuple(sorted(reason_set)),
                exclusion_breakdown=agg_breakdown,
                flags_applied=tuple(
                    k for k, v in first.variables.items() if v.semantics == "qa_flag"
                ),
            )
            agg_granule_id = f"{first.granule_id}+{len(outcomes) - 1}"
            agg_source_id = f"{req.product}_{min_start:%Y%m%d}_{max_end:%Y%m%d}_{len(outcomes)}"
            unreliable_all = total_valid_all == 0

        grouped_obs: dict[str, dict[datetime, list[_ModisVarObs]]] = {}
        unit_by_var: dict[str, str] = {}
        for item in outcomes:
            for obs in item.observations:
                unit_by_var[obs.canonical_name] = obs.units
                grouped_obs.setdefault(obs.canonical_name, {}).setdefault(obs.timestamp, []).append(
                    obs
                )

        time_series_ext: dict[str, Any] = {}
        for canon_var, ts_buckets in grouped_obs.items():
            ts_list: list[datetime] = []
            val_list: list[float | None] = []
            valid_counts: list[int] = []
            total_counts: list[int] = []
            qa_keys = sorted(
                {k for bucket in ts_buckets.values() for o in bucket for k in o.qa_values}
            )
            qa_series: dict[str, list[int | float | None]] = {k: [] for k in qa_keys}

            for dt in sorted(ts_buckets):
                bucket = ts_buckets[dt]
                ts_list.append(dt)
                valid_obs = [o for o in bucket if o.value is not None]
                tot_vpx = sum(o.valid_pixels for o in bucket)
                tot_apx = sum(o.total_pixels for o in bucket)
                valid_counts.append(tot_vpx)
                total_counts.append(tot_apx)
                if valid_obs:
                    weight_sum = sum(o.valid_pixels for o in valid_obs)
                    if weight_sum > 0:
                        weighted_num = sum(
                            float(o.value) * o.valid_pixels
                            for o in valid_obs
                            if o.value is not None
                        )
                        val_list.append(weighted_num / weight_sum)
                    else:
                        unweighted_sum = sum(
                            float(o.value) for o in valid_obs if o.value is not None
                        )
                        val_list.append(unweighted_sum / len(valid_obs))
                else:
                    val_list.append(None)

                for qk in qa_keys:
                    chosen_q: int | None = None
                    for o in valid_obs or bucket:
                        if o.qa_values.get(qk) is not None:
                            chosen_q = o.qa_values[qk]
                            break
                    qa_series[qk].append(chosen_q)

            time_series_ext[canon_var] = build_time_series_extension(
                timestamps=ts_list,
                values=val_list,
                units=unit_by_var.get(canon_var),
                qa_layers=qa_series,
                valid_pixel_counts=valid_counts,
                total_pixel_counts=total_counts,
                is_scaled=True,
            )

        crs = first.decoded.crs or MODIS_SINUSOIDAL_WKT
        version = req.product.split(".", 1)[1]
        spatial_res = _PRODUCT_RESOLUTION.get(req.product, "250 m")
        prov_meta = dict(first.src_meta)
        if len(outcomes) > 1:
            prov_meta["granule_ids"] = [item.granule_id for item in outcomes]
            prov_meta["all_source_urls"] = [item.final_url for item in outcomes]
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=agg_source_id,
            provider=self.provider,
            product=req.product,
            product_version=version,
            granule_id=agg_granule_id,
            variables=first.variables,
            units={k: v.units for k, v in first.variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                crs,
                first.decoded.grid.bounds if first.decoded.grid else None,
                first.decoded.grid,
                spatial_resolution=spatial_res,
            ),
            temporal_metadata=temporal,
            quality_metadata=qa_meta,
            assets=all_assets,
            provenance=build_provenance(
                self.provider,
                req.product,
                version,
                first.final_url,
                granule_id=agg_granule_id,
                source_metadata=prov_meta,
            ),
            extensions={
                "composite_days": comp_days,
                "authalic_sphere_radius_m": 6371007.181,
                "unreliable_all_pixels_rejected": unreliable_all,
                "time_series": time_series_ext,
                "ingestion_summary": {
                    "product": req.product,
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
