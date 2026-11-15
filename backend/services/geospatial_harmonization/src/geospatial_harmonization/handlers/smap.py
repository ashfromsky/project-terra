"""SMAP SPL3SMP_E handler distinguishing 9 km EASE-Grid 2.0 from ~36 km native footprint."""

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

import h5py
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

_EASE2_CRS = {"global": "EPSG:6933", "polar": "EPSG:6931"}
_SMAP_SPATIAL_RESOLUTION = "9 km EASE-Grid 2.0 (~36 km native radiometer footprint)"
_SMAP_LARGE_HDF5_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class SmapQaEvaluation:
    """SMAP quality evaluation summary combining retrieval_qual_flag, surface_flag, and fill."""

    valid_fraction: float | None
    missing_fraction: float | None
    excluded_count: int
    exclusion_breakdown: dict[str, int]
    reasons: tuple[str, ...]
    flags_applied: tuple[str, ...]


def decode_smap_surface_flag(surface_flag: np.ndarray) -> dict[str, np.ndarray]:
    """Decode SMAP SPL3SMP_E 16-bit surface_flag masks (frozen ground, snow/ice, water)."""
    sf = np.asarray(surface_flag, dtype=np.uint16)
    valid = sf != np.uint16(65535)
    water = valid & ((sf & np.uint16(0b11)) != 0)
    snow_ice = valid & (((sf >> np.uint16(5)) & np.uint16(0b11)) != 0)
    frozen_ground = valid & (((sf >> np.uint16(7)) & np.uint16(0b11)) != 0)
    return {
        "water_body": water,
        "snow_ice": snow_ice,
        "frozen_ground": frozen_ground,
    }


def _select_smap_hdf5_variables(
    path: Path, overpass: Literal["AM", "PM"]
) -> tuple[str, ...] | None:
    if path.stat().st_size < _SMAP_LARGE_HDF5_BYTES:
        return None
    suffix = "_pm" if overpass == "PM" else ""
    group_prefix = f"Soil_Moisture_Retrieval_Data_{overpass}"
    targets = {
        f"soil_moisture{suffix}",
        f"retrieval_qual_flag{suffix}",
        f"surface_flag{suffix}",
        f"surface_temperature{suffix}",
        f"vegetation_water_content{suffix}",
        f"latitude{suffix}",
        f"longitude{suffix}",
    }
    matched: list[str] = []
    with h5py.File(path, "r") as h5f:
        if group_prefix not in h5f:
            return None
        grp = h5f[group_prefix]
        if not isinstance(grp, h5py.Group):
            return None
        for key in grp:
            if key.lower() in targets:
                matched.append(f"{group_prefix}/{key}")
    return tuple(matched) if matched else None


def _pick_overpass_variable(
    variables: Mapping[str, VariableSpec], overpass: Literal["AM", "PM"], exact_leaf: str
) -> str | None:
    suffix = "_pm" if overpass == "PM" else ""
    wanted_leaf = f"{exact_leaf}{suffix}".lower()
    group_hint = f"_{overpass.lower()}/"
    candidates = [
        name
        for name in variables
        if name.rsplit("/", 1)[-1].lower() in (wanted_leaf, exact_leaf.lower())
    ]
    if not candidates:
        return None
    for name in candidates:
        if group_hint in name.lower() or name.rsplit("/", 1)[-1].lower() == wanted_leaf:
            return name
    return candidates[0]


def evaluate_smap_quality(
    variables: Mapping[str, VariableSpec],
    arrays: Mapping[str, object],
    *,
    overpass: Literal["AM", "PM"],
) -> SmapQaEvaluation:
    """Evaluate SMAP fill, physical bounds, retrieval_qual_flag (0/8), and surface_flag."""
    sm_name = _pick_overpass_variable(variables, overpass, "soil_moisture")
    qf_name = _pick_overpass_variable(variables, overpass, "retrieval_qual_flag")
    sf_name = _pick_overpass_variable(variables, overpass, "surface_flag")

    ref_shape: tuple[int, ...] | None = None
    for cand in (sm_name, qf_name, sf_name):
        if cand is not None and cand in arrays:
            ref_shape = np.asarray(arrays[cand]).shape
            break
    if ref_shape is None:
        return SmapQaEvaluation(None, None, 0, {}, (), ())
    total = int(np.prod(ref_shape))
    if total == 0:
        raise QualityPolicyViolationError("SMAP array contains zero elements")

    masks: dict[str, np.ndarray] = {}
    flags_applied: list[str] = []

    if sm_name is not None and sm_name in arrays:
        sm_arr = np.asarray(arrays[sm_name], dtype=np.float64)
        sm_spec = variables[sm_name]
        fill_mask = ~np.isfinite(sm_arr)
        if sm_spec.nodata is not None:
            fill_mask |= sm_arr == float(sm_spec.nodata)
        out_of_range = (~fill_mask) & ((sm_arr < 0.0) | (sm_arr > 0.7))
        masks["fill_nodata"] = fill_mask
        masks["out_of_range"] = out_of_range

    if qf_name is not None and qf_name in arrays:
        qf_arr = np.asarray(arrays[qf_name])
        if qf_arr.shape != ref_shape:
            raise QualityPolicyViolationError("SMAP retrieval_qual_flag shape mismatch")
        qf_spec = variables[qf_name]
        qf_fill = qf_arr == (qf_spec.nodata if qf_spec.nodata is not None else 65535)
        recommended = np.isin(qf_arr, (0, 8)) & (~qf_fill)
        not_attempted = (
            (~qf_fill) & (~recommended) & ((qf_arr.astype(np.uint16) & np.uint16(0x02)) != 0)
        )
        failed = (
            (~qf_fill)
            & (~recommended)
            & (~not_attempted)
            & ((qf_arr.astype(np.uint16) & np.uint16(0x04)) != 0)
        )
        other_bad = (~qf_fill) & (~recommended) & (~not_attempted) & (~failed)
        masks["retrieval_fill"] = qf_fill
        masks["retrieval_skipped"] = not_attempted
        masks["retrieval_failed"] = failed
        masks["retrieval_not_recommended"] = other_bad
        flags_applied.append("retrieval_qual_flag in {0, 8}")

    if sf_name is not None and sf_name in arrays:
        sf_arr = np.asarray(arrays[sf_name])
        if sf_arr.shape != ref_shape:
            raise QualityPolicyViolationError("SMAP surface_flag shape mismatch")
        decoded_sf = decode_smap_surface_flag(sf_arr)
        for key, mask in decoded_sf.items():
            masks[key] = mask
        flags_applied.append("surface_flag(frozen_ground, snow_ice, water_body)")

    excluded_mask = np.zeros(ref_shape, dtype=bool)
    for mask in masks.values():
        excluded_mask |= mask

    breakdown = {
        reason: count
        for reason, mask in masks.items()
        if (count := int(np.count_nonzero(mask))) > 0
    }
    excluded_count = int(np.count_nonzero(excluded_mask))
    valid_frac = (total - excluded_count) / total
    missing_frac = excluded_count / total
    reasons = tuple(sorted(breakdown))
    if excluded_count == total:
        reasons = (*reasons, "all_pixels_unavailable_or_frozen")

    return SmapQaEvaluation(
        valid_fraction=valid_frac,
        missing_fraction=missing_frac,
        excluded_count=excluded_count,
        exclusion_breakdown=breakdown,
        reasons=reasons,
        flags_applied=tuple(flags_applied),
    )


class SMAPPayload(BaseModel):
    """Input schema for SMAP SPL3SMP_E enhanced 9 km Level-3 soil moisture retrieval."""

    model_config = ConfigDict(extra="forbid")

    product: Literal["SPL3SMP_E.006"] = "SPL3SMP_E.006"
    granule_url: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    overpass: Literal["AM", "PM"] = "AM"
    domain: Literal["global", "polar"] = "global"
    data_format: DataFormat = "hdf5"
    variables: tuple[str, ...] | None = None


class SMAPHandler:
    """DataHandler for NASA SMAP SPL3SMP_E v006 preserving Backus-Gilbert & QA semantics."""

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
        return "smap"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("SPL3SMP_E.006",)

    async def discover(
        self,
        *,
        product: str,
        bbox: tuple[float, float, float, float],
        start_time: datetime,
        end_time: datetime,
        limit: int = 10,
    ) -> tuple[DiscoveryResult, ...]:
        """Discover SMAP SPL3SMP_E granules from NASA CMR for an AOI and time window."""
        return await discover_cmr_observations(
            enabled=self._settings.is_provider_enabled(self.provider),
            provider=self.provider,
            product=product,
            cmr_url=self._cmr_url,
            token=self._token,
            extensions=(".h5", ".hdf5", ".he5"),
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
        """Fetch SMAP granule, classify QA/surface flags, and record native footprint notes."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "SMAP provider is disabled by configuration (SMAP_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(SMAPPayload, payload)
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
                t0 + timedelta(days=1),
                (".h5", ".hdf5", ".he5"),
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

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_smap_"))
        preferred_name = (
            cmr_granule.producer_granule_id
            if cmr_granule
            and cmr_granule.producer_granule_id.lower().endswith((".h5", ".hdf5", ".he5"))
            else Path(urlparse(url).path).name or "SMAP_SPL3SMP_E.h5"
        )
        path, asset, final_url = await safe_fetch_to_file(
            url,
            base_dir,
            filename=preferred_name,
            fallback_filename="SMAP_SPL3SMP_E.h5",
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
        selected_vars = req.variables or _select_smap_hdf5_variables(path, req.overpass)
        decoded = self._readers.read(asset, path, variables=selected_vars)

        variables: dict[str, VariableSpec] = {}
        for name, spec in decoded.variables.items():
            leaf = name.rsplit("/", 1)[-1].lower()
            if (
                "retrieval_qual_flag" in leaf
                or "surface_flag" in leaf
                or spec.semantics == "qa_flag"
            ):
                variables[name] = replace(
                    spec, semantics="qa_flag", scale_factor=None, add_offset=None
                )
            elif leaf in ("soil_moisture", "soil_moisture_pm"):
                variables[name] = replace(
                    spec,
                    units="cm^3/cm^3" if spec.units == "1" else spec.units,
                    semantics="continuous_intensive",
                    valid_range=(0.0, 0.7),
                )
            else:
                variables[name] = spec

        qa_eval = evaluate_smap_quality(variables, decoded.arrays, overpass=req.overpass)
        win_start = cmr_granule.time_start if cmr_granule and cmr_granule.time_start else t0
        win_end = (
            cmr_granule.time_end
            if cmr_granule and cmr_granule.time_end and cmr_granule.time_end > win_start
            else win_start + timedelta(days=1)
        )
        crs = decoded.crs or _EASE2_CRS[req.domain]
        granule_id = (
            (cmr_granule.producer_granule_id if cmr_granule else None)
            or str(decoded.attributes.get("GranuleID") or "").strip()
            or fname
        )
        src_meta: dict[str, object] = {}
        if cmr_granule is not None:
            src_meta["cmr"] = dict(cmr_granule.source_metadata)
        for key in ("ShortName", "VersionID", "rangeBeginningDateTime", "rangeEndingDateTime"):
            if key in decoded.attributes:
                src_meta[key] = decoded.attributes[key]

        prov = replace(
            build_provenance(
                self.provider,
                req.product,
                "006",
                final_url,
                granule_id=granule_id,
                source_metadata=src_meta,
            ),
            notes=(
                "Nominal 9 km EASE-Grid 2.0 posting derived via Backus-Gilbert optimal "
                "interpolation from ~36 km native radiometer footprint.",
            ),
        )
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=asset.checksum_sha256 or fname,
            provider=self.provider,
            product=req.product,
            product_version="006",
            granule_id=granule_id,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                crs,
                decoded.grid.bounds if decoded.grid else None,
                decoded.grid,
                spatial_resolution=_SMAP_SPATIAL_RESOLUTION,
            ),
            temporal_metadata=TemporalSpec(
                win_start,
                win_end,
                "daily",
                "interval",
                acquisition_timestamp=win_start,
            ),
            quality_metadata=QualityMetadata(
                qa_policy="smap_retrieval_qual_and_surface_flags",
                valid_observation_fraction=qa_eval.valid_fraction,
                missing_data_fraction=qa_eval.missing_fraction,
                excluded_count=qa_eval.excluded_count,
                exclusion_reasons=qa_eval.reasons,
                exclusion_breakdown=qa_eval.exclusion_breakdown,
                flags_applied=qa_eval.flags_applied,
            ),
            assets=(asset,),
            provenance=prov,
            extensions={
                "overpass": req.overpass,
                "domain": req.domain,
                "nominal_grid_spacing_m": 9000,
                "native_footprint_km": 36.0,
                "interpolation_method": "Backus-Gilbert",
            },
        )
