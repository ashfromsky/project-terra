"""SMAP SPL3SMP_E handler distinguishing 9 km EASE-Grid 2.0 from ~36 km native footprint."""

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
from geospatial_harmonization.domain.models.dataset import (
    DataFormat,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.handlers.base import (
    build_provenance,
    discover_cmr_granule_url,
    earthdata_hosts_for,
    parse_handler_payload,
    safe_fetch_bytes,
    write_raw_asset,
)
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry

_EASE2_CRS = {"global": "EPSG:6933", "polar": "EPSG:6931"}


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
        self._cmr_url = cfg.cmr_base_url.rstrip("/")
        self._token = cfg.earthdata_token.get_secret_value() if cfg.earthdata_token else None
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._readers = reader_registry or build_default_reader_registry()
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "smap"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("SPL3SMP_E.006",)

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch SMAP granule, classify QA flags (0 and 8), and record native footprint notes."""
        req = parse_handler_payload(SMAPPayload, payload)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)
        url = req.granule_url or await discover_cmr_granule_url(
            self._cmr_url,
            req.product,
            t0,
            t0 + timedelta(days=1),
            (".h5", ".hdf5", ".he5"),
            bbox=req.bbox,
            headers=headers,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        raw, final_url, media = await safe_fetch_bytes(
            url,
            allowed_hosts=earthdata_hosts_for(self._cmr_url),
            headers=headers,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_smap_"))
        fname = Path(urlparse(final_url).path).name or "SMAP_SPL3SMP_E.h5"
        path, asset = write_raw_asset(base_dir, fname, raw, req.data_format, media)
        decoded = self._readers.read(asset, path, variables=req.variables)

        variables: dict[str, VariableSpec] = {}
        qf_name: str | None = None
        for name, spec in decoded.variables.items():
            leaf = name.rsplit("/", 1)[-1].lower()
            if "retrieval_qual_flag" in leaf or spec.semantics == "qa_flag":
                if qf_name is None or req.overpass.lower() in name.lower():
                    qf_name = name
                variables[name] = replace(
                    spec, semantics="qa_flag", scale_factor=None, add_offset=None
                )
            elif "soil_moisture" in leaf:
                variables[name] = replace(
                    spec,
                    units="cm^3/cm^3" if spec.units == "1" else spec.units,
                    semantics="continuous_intensive",
                    valid_range=(0.0, 0.7),
                )
            else:
                variables[name] = spec

        valid_frac: float | None = None
        excluded = 0
        if qf_name is not None and qf_name in decoded.arrays:
            qf_arr = np.asarray(decoded.arrays[qf_name])
            recommended = np.isin(qf_arr, (0, 8))
            if qf_arr.size > 0:
                valid_frac = float(np.count_nonzero(recommended) / qf_arr.size)
                excluded = int(qf_arr.size - np.count_nonzero(recommended))

        t0 = req.start_time.astimezone(UTC)
        crs = decoded.crs or _EASE2_CRS[req.domain]
        prov = replace(
            build_provenance(self.provider, req.product, "006", final_url),
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
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster", crs, decoded.grid.bounds if decoded.grid else None, decoded.grid
            ),
            temporal_metadata=TemporalSpec(t0, t0 + timedelta(days=1), "daily", "interval"),
            quality_metadata=QualityMetadata(
                qa_policy="smap_retrieval_qual_flag_0_or_8",
                valid_observation_fraction=valid_frac,
                excluded_count=excluded,
                exclusion_reasons=("retrieval_qual_flag not in {0, 8}",) if excluded else (),
                flags_applied=("retrieval_qual_flag in {0, 8}",),
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
