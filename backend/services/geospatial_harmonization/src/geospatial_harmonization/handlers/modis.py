"""MODIS handler (MOD13Q1.061, MOD11A2.061) with Sinusoidal CRS and bitmask QA screening."""

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict
from pyproj import CRS

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
    valid_mask = ~excluded

    breakdown = {
        reason: count
        for reason, mask in reasons_masks.items()
        if (count := int(np.count_nonzero(mask))) > 0
    }
    excluded_count = int(np.count_nonzero(excluded))
    valid_count = int(np.count_nonzero(valid_mask))
    total = int(raw.size)
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


class MODISPayload(BaseModel):
    """Input schema for MODIS product granule ingestion."""

    model_config = ConfigDict(extra="forbid")

    product: Literal["MOD13Q1.061", "MOD11A2.061"]
    granule_url: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    data_format: DataFormat = "hdf4"
    variables: tuple[str, ...] | None = None


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
        """Download MODIS granule via CMR/Earthdata, apply QA screening, and build dataset."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "MODIS provider is disabled by configuration (MODIS_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(MODISPayload, payload)
        comp_days, cadence, template_specs = _PRODUCT_SPECS[req.product]
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)

        cmr_granule: CmrGranule | None = None
        if req.granule_url:
            url = req.granule_url
        else:
            granules = await discover_cmr_granules(
                self._cmr_url,
                req.product,
                t0,
                t0 + timedelta(days=comp_days),
                (".hdf", ".tif", ".tiff"),
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

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_modis_"))
        preferred_name = (
            cmr_granule.producer_granule_id
            if cmr_granule and cmr_granule.producer_granule_id.endswith((".hdf", ".tif", ".tiff"))
            else Path(urlparse(url).path).name or f"{req.product}.hdf"
        )
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
        decoded = self._readers.read(asset, path, variables=req.variables)

        variables: dict[str, VariableSpec] = {}
        for name, dec_spec in decoded.variables.items():
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
            (cmr_granule.producer_granule_id if cmr_granule else None) or local_granule_id or fname
        )

        win_start = cmr_granule.time_start if cmr_granule and cmr_granule.time_start else t0
        win_end = (
            cmr_granule.time_end
            if cmr_granule and cmr_granule.time_end and cmr_granule.time_end > win_start
            else win_start + timedelta(days=comp_days)
        )
        temporal = TemporalSpec(
            win_start,
            win_end,
            cadence,
            "composite",
            composite_days=comp_days,
            acquisition_timestamp=win_start,
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

        crs = decoded.crs or MODIS_SINUSOIDAL_WKT
        version = req.product.split(".", 1)[1]
        spatial_res = _PRODUCT_RESOLUTION.get(req.product, "250 m")
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=asset.checksum_sha256 or fname,
            provider=self.provider,
            product=req.product,
            product_version=version,
            granule_id=granule_id,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                crs,
                decoded.grid.bounds if decoded.grid else None,
                decoded.grid,
                spatial_resolution=spatial_res,
            ),
            temporal_metadata=temporal,
            quality_metadata=QualityMetadata(
                "modis_qa_bitmask_screened",
                valid_observation_fraction=qa_eval.valid_fraction,
                missing_data_fraction=qa_eval.missing_fraction,
                excluded_count=qa_eval.excluded_count,
                exclusion_reasons=qa_eval.reasons,
                exclusion_breakdown=qa_eval.exclusion_breakdown,
                flags_applied=tuple(k for k, v in variables.items() if v.semantics == "qa_flag"),
            ),
            assets=(asset,),
            provenance=build_provenance(
                self.provider,
                req.product,
                version,
                final_url,
                granule_id=granule_id,
                source_metadata=src_meta,
            ),
            extensions={
                "composite_days": comp_days,
                "authalic_sphere_radius_m": 6371007.181,
                "unreliable_all_pixels_rejected": qa_eval.valid_fraction == 0.0,
            },
        )
