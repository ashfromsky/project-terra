"""SMAP SPL3SMP_E handler distinguishing 9 km EASE-Grid 2.0 from ~36 km native footprint."""

import asyncio
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


def _evaluate_smap_pixel_masks(
    variables: Mapping[str, VariableSpec],
    arrays: Mapping[str, object],
    *,
    overpass: Literal["AM", "PM"],
) -> tuple[
    str | None,
    str | None,
    str | None,
    tuple[int, ...] | None,
    dict[str, np.ndarray],
    np.ndarray | None,
    list[str],
]:
    sm_name = _pick_overpass_variable(variables, overpass, "soil_moisture")
    qf_name = _pick_overpass_variable(variables, overpass, "retrieval_qual_flag")
    sf_name = _pick_overpass_variable(variables, overpass, "surface_flag")

    ref_shape: tuple[int, ...] | None = None
    for cand in (sm_name, qf_name, sf_name):
        if cand is not None and cand in arrays:
            ref_shape = np.asarray(arrays[cand]).shape
            break
    if ref_shape is None:
        return sm_name, qf_name, sf_name, None, {}, None, []
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

    return sm_name, qf_name, sf_name, ref_shape, masks, ~excluded_mask, flags_applied


def evaluate_smap_quality(
    variables: Mapping[str, VariableSpec],
    arrays: Mapping[str, object],
    *,
    overpass: Literal["AM", "PM"],
) -> SmapQaEvaluation:
    """Evaluate SMAP fill, physical bounds, retrieval_qual_flag (0/8), and surface_flag."""
    _, _, _, ref_shape, masks, valid_mask, flags_applied = _evaluate_smap_pixel_masks(
        variables, arrays, overpass=overpass
    )
    if ref_shape is None or valid_mask is None:
        return SmapQaEvaluation(None, None, 0, {}, (), ())

    total = int(np.prod(ref_shape))
    breakdown = {
        reason: count
        for reason, mask in masks.items()
        if (count := int(np.count_nonzero(mask))) > 0
    }
    excluded_count = int(np.count_nonzero(~valid_mask))
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


def _representative_smap_qa(
    arr: np.ndarray,
    eff_mask: np.ndarray,
    aoi_mask: np.ndarray | None,
) -> int | None:
    if arr.shape != eff_mask.shape:
        return None
    if np.any(eff_mask):
        sample = arr[eff_mask]
    elif aoi_mask is not None and np.any(aoi_mask):
        sample = arr[aoi_mask]
    else:
        sample = arr.ravel()
    if sample.size == 0:
        return None
    vals, counts = np.unique(sample, return_counts=True)
    return int(vals[int(np.argmax(counts))])


def _parse_smap_start_attr(attrs: Mapping[str, object]) -> datetime | None:
    raw = attrs.get("rangeBeginningDateTime")
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class _SmapGranuleOutcome:
    url: str
    final_url: str
    asset: AssetReference
    decoded: DecodedDataset
    variables: dict[str, VariableSpec]
    qa_eval: SmapQaEvaluation
    granule_id: str
    win_start: datetime
    win_end: datetime
    mean_sm: float | None
    rqf_code: int | None
    sf_code: int | None
    aoi_valid_px: int
    aoi_total_px: int
    total_count: int
    src_meta: dict[str, object]


class SMAPPayload(BaseModel):
    """Input schema for SMAP SPL3SMP_E enhanced 9 km Level-3 soil moisture retrieval."""

    model_config = ConfigDict(extra="forbid")

    product: Literal["SPL3SMP_E.006"] = "SPL3SMP_E.006"
    granule_url: str | None = None
    granule_urls: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    start_time: datetime
    end_time: datetime | None = None
    max_granules: int = Field(default=12, ge=1, le=256)
    max_concurrency: int = Field(default=3, ge=1, le=8)
    overpass: Literal["AM", "PM"] = "AM"
    domain: Literal["global", "polar"] = "global"
    data_format: DataFormat = "hdf5"
    variables: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "SMAPPayload":
        if self.bbox is not None:
            validate_wgs84_bbox(self.bbox)
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time cannot precede start_time")
        return self


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
        """Fetch SMAP granule batch, classify QA/surface flags, and assemble time series."""
        if not self._settings.is_provider_enabled(self.provider):
            raise ProviderDisabledError(
                "SMAP provider is disabled by configuration (SMAP_ENABLED=false)",
                provider=self.provider,
            )
        req = parse_handler_payload(SMAPPayload, payload)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)

        explicit_urls: list[str] = []
        seen_urls: set[str] = set()
        for raw_u in [*([req.granule_url] if req.granule_url else []), *req.granule_urls]:
            if raw_u and raw_u not in seen_urls:
                seen_urls.add(raw_u)
                explicit_urls.append(raw_u)

        targets: list[tuple[int, str, CmrGranule | None]] = []
        selection_meta: dict[str, object] = {
            "discovered_count": len(explicit_urls),
            "selection_strategy": "explicit_urls",
        }
        if explicit_urls:
            for idx, target_url in enumerate(explicit_urls[: req.max_granules]):
                targets.append((idx, target_url, None))
        else:
            t1 = (
                req.end_time.astimezone(UTC) if req.end_time is not None else t0 + timedelta(days=1)
            )
            granules = await discover_cmr_granules(
                self._cmr_url,
                req.product,
                t0,
                t1,
                (".h5", ".hdf5", ".he5"),
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

        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_smap_"))
        is_batch = len(targets) > 1

        async def _ingest_one(item: tuple[int, str, CmrGranule | None]) -> _SmapGranuleOutcome:
            idx, url, cmr_granule = item
            base_pref = (
                cmr_granule.producer_granule_id
                if cmr_granule
                and cmr_granule.producer_granule_id.lower().endswith((".h5", ".hdf5", ".he5"))
                else Path(urlparse(url).path).name or "SMAP_SPL3SMP_E.h5"
            )
            preferred_name = f"{idx:03d}_{base_pref}" if is_batch else base_pref
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
            selected_vars = req.variables or await asyncio.to_thread(
                _select_smap_hdf5_variables, path, req.overpass
            )
            decoded = await asyncio.to_thread(
                self._readers.read, asset, path, variables=selected_vars
            )

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
                        valid_range=(0.0, 1.0),
                    )
                else:
                    variables[name] = spec

            qa_eval = evaluate_smap_quality(variables, decoded.arrays, overpass=req.overpass)
            sm_name, qf_name, sf_name, ref_shape, _, valid_mask, _ = _evaluate_smap_pixel_masks(
                variables, decoded.arrays, overpass=req.overpass
            )

            mean_sm: float | None = None
            rqf_code: int | None = None
            sf_code: int | None = None
            aoi_valid_px = 0
            aoi_total_px = int(np.prod(ref_shape)) if ref_shape else 0
            if sm_name is not None and sm_name in decoded.arrays and valid_mask is not None:
                sm_arr = np.asarray(decoded.arrays[sm_name], dtype=np.float64)
                aoi_mask: np.ndarray | None = None
                if sm_arr.ndim >= 2:
                    aoi_mask = extract_aoi_mask_for_decoded(
                        decoded, (sm_arr.shape[-2], sm_arr.shape[-1]), req.bbox
                    )
                if aoi_mask is not None and sm_arr.ndim == 2:
                    eff_mask = valid_mask & aoi_mask
                    aoi_total_px = int(np.count_nonzero(aoi_mask))
                else:
                    eff_mask = valid_mask
                    aoi_total_px = int(valid_mask.size)
                aoi_valid_px = int(np.count_nonzero(eff_mask))
                mean_sm = float(np.mean(sm_arr[eff_mask])) if aoi_valid_px > 0 else None
                if qf_name is not None and qf_name in decoded.arrays:
                    rqf_code = _representative_smap_qa(
                        np.asarray(decoded.arrays[qf_name]), eff_mask, aoi_mask
                    )
                if sf_name is not None and sf_name in decoded.arrays:
                    sf_code = _representative_smap_qa(
                        np.asarray(decoded.arrays[sf_name]), eff_mask, aoi_mask
                    )

            win_start = (
                cmr_granule.time_start
                if cmr_granule and cmr_granule.time_start
                else (_parse_smap_start_attr(decoded.attributes) or (t0 + timedelta(days=idx)))
            )
            win_end = (
                cmr_granule.time_end
                if cmr_granule and cmr_granule.time_end and cmr_granule.time_end > win_start
                else win_start + timedelta(days=1)
            )
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

            return _SmapGranuleOutcome(
                url=url,
                final_url=final_url,
                asset=asset,
                decoded=decoded,
                variables=variables,
                qa_eval=qa_eval,
                granule_id=granule_id,
                win_start=win_start,
                win_end=win_end,
                mean_sm=mean_sm,
                rqf_code=rqf_code,
                sf_code=sf_code,
                aoi_valid_px=aoi_valid_px,
                aoi_total_px=aoi_total_px,
                total_count=int(np.prod(ref_shape)) if ref_shape else 0,
                src_meta=src_meta,
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
        crs = first.decoded.crs or _EASE2_CRS[req.domain]
        min_start = min(item.win_start for item in outcomes)
        max_end = max(item.win_end for item in outcomes)

        if len(outcomes) == 1:
            qa_meta = QualityMetadata(
                qa_policy="smap_retrieval_qual_and_surface_flags",
                valid_observation_fraction=first.qa_eval.valid_fraction,
                missing_data_fraction=first.qa_eval.missing_fraction,
                excluded_count=first.qa_eval.excluded_count,
                exclusion_reasons=first.qa_eval.reasons,
                exclusion_breakdown=first.qa_eval.exclusion_breakdown,
                flags_applied=first.qa_eval.flags_applied,
            )
            agg_granule_id = first.granule_id
            agg_source_id = first.asset.checksum_sha256 or Path(first.url).name
        else:
            total_px_all = sum(item.total_count for item in outcomes)
            excluded_all = sum(item.qa_eval.excluded_count for item in outcomes)
            agg_breakdown: dict[str, int] = {}
            reason_set: set[str] = set()
            flags_seen: list[str] = []
            for item in outcomes:
                for r_name, r_cnt in item.qa_eval.exclusion_breakdown.items():
                    agg_breakdown[r_name] = agg_breakdown.get(r_name, 0) + r_cnt
                reason_set.update(item.qa_eval.reasons)
                for fl in item.qa_eval.flags_applied:
                    if fl not in flags_seen:
                        flags_seen.append(fl)
            valid_frac = (total_px_all - excluded_all) / total_px_all if total_px_all > 0 else None
            missing_frac = excluded_all / total_px_all if total_px_all > 0 else None
            qa_meta = QualityMetadata(
                qa_policy="smap_retrieval_qual_and_surface_flags",
                valid_observation_fraction=valid_frac,
                missing_data_fraction=missing_frac,
                excluded_count=excluded_all,
                exclusion_reasons=tuple(sorted(reason_set)),
                exclusion_breakdown=agg_breakdown,
                flags_applied=tuple(flags_seen),
            )
            agg_granule_id = f"{first.granule_id}+{len(outcomes) - 1}"
            agg_source_id = f"{req.product}_{min_start:%Y%m%d}_{max_end:%Y%m%d}_{len(outcomes)}"

        canon_var = "soil_moisture_pm" if req.overpass == "PM" else "soil_moisture"
        ts_list = [item.win_start for item in outcomes]
        val_list = [item.mean_sm for item in outcomes]
        rqf_list: list[int | float | None] = [item.rqf_code for item in outcomes]
        sf_list: list[int | float | None] = [item.sf_code for item in outcomes]
        qa_layers_ext: dict[str, list[int | float | None]] = {}
        if any(q is not None for q in rqf_list):
            qa_layers_ext["retrieval_qual_flag"] = rqf_list
        if any(s is not None for s in sf_list):
            qa_layers_ext["surface_flag"] = sf_list

        sm_unit = next(
            (
                v.units
                for v in first.variables.values()
                if v.name.rsplit("/", 1)[-1].lower() in ("soil_moisture", "soil_moisture_pm")
            ),
            "cm^3/cm^3",
        )
        time_series_ext = {
            canon_var: build_time_series_extension(
                timestamps=ts_list,
                values=val_list,
                units=sm_unit,
                qa_layers=qa_layers_ext,
                overpass_tags=[req.overpass] * len(outcomes),
                valid_pixel_counts=[item.aoi_valid_px for item in outcomes],
                total_pixel_counts=[item.aoi_total_px for item in outcomes],
                is_scaled=True,
            )
        }

        prov_meta = dict(first.src_meta)
        if len(outcomes) > 1:
            prov_meta["granule_ids"] = [item.granule_id for item in outcomes]
            prov_meta["all_source_urls"] = [item.final_url for item in outcomes]

        prov = replace(
            build_provenance(
                self.provider,
                req.product,
                "006",
                first.final_url,
                granule_id=agg_granule_id,
                source_metadata=prov_meta,
            ),
            notes=(
                "Nominal 9 km EASE-Grid 2.0 posting derived via Backus-Gilbert optimal "
                "interpolation from ~36 km native radiometer footprint.",
            ),
        )
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=agg_source_id,
            provider=self.provider,
            product=req.product,
            product_version="006",
            granule_id=agg_granule_id,
            variables=first.variables,
            units={k: v.units for k, v in first.variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                crs,
                first.decoded.grid.bounds if first.decoded.grid else None,
                first.decoded.grid,
                spatial_resolution=_SMAP_SPATIAL_RESOLUTION,
            ),
            temporal_metadata=TemporalSpec(
                min_start,
                max_end,
                "daily",
                "interval",
                acquisition_timestamp=first.win_start,
            ),
            quality_metadata=qa_meta,
            assets=tuple(item.asset for item in outcomes),
            provenance=prov,
            extensions={
                "overpass": req.overpass,
                "overpass_mode": f"{req.overpass.lower()}_only",
                "domain": req.domain,
                "nominal_grid_spacing_m": 9000,
                "native_footprint_km": 36.0,
                "interpolation_method": "Backus-Gilbert",
                "time_series": time_series_ext,
                "ingestion_summary": {
                    "product": req.product,
                    "overpass": req.overpass,
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
