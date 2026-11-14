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
from geospatial_harmonization.transformations.temporal import integrate_rate_to_depth

IMERGProduct = Literal["GPM_3IMERGHH.07", "GPM_3IMERGHH.06", "GPM_3IMERGHHE.07", "GPM_3IMERGHHL.07"]
RunType = Literal["Early", "Late", "Final"]

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
        self._cmr_url = cfg.cmr_base_url.rstrip("/")
        self._token = cfg.earthdata_token.get_secret_value() if cfg.earthdata_token else None
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._readers = reader_registry or build_default_reader_registry()
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "gpm_imerg"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("GPM_3IMERGHH.07", "GPM_3IMERGHH.06", "GPM_3IMERGHHE.07", "GPM_3IMERGHHL.07")

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch IMERG half-hour granule, track missing counts, and record depth summary."""
        req = parse_handler_payload(GPMIMERGPayload, payload)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)
        t1 = t0 + timedelta(minutes=30)
        url = req.granule_url or await discover_cmr_granule_url(
            self._cmr_url,
            req.product,
            t0,
            t1,
            (".nc", ".nc4", ".h5", ".hdf5"),
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
        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_imerg_"))
        fname = Path(urlparse(final_url).path).name or f"{req.product}.nc4"
        path, asset = write_raw_asset(base_dir, fname, raw, req.data_format, media)
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
                variables[name] = replace(
                    spec,
                    units="mm/hr" if spec.units == "1" else spec.units,
                    semantics="continuous_extensive",
                    attributes={
                        **spec.attributes,
                        "interval_duration_hours": 0.5,
                        "supports_rate_to_depth": True,
                    },
                )
            else:
                variables[name] = spec

        temporal = TemporalSpec(t0, t1, "30min", "interval", aggregation="rate_to_depth_sum")
        precip_spec = variables[precip_key]
        p_arr = np.asarray(decoded.arrays[precip_key])
        depth_res = integrate_rate_to_depth(
            [p_arr], [temporal], temporal, nodata=precip_spec.nodata
        )
        excluded = int(p_arr.size - depth_res.valid_pixels)
        valid_frac = depth_res.valid_pixels / p_arr.size if p_arr.size > 0 else None
        run_type = _infer_run_type(req.product, final_url, req.run_type)
        ver = req.product.split(".", 1)[1]

        mean_depth = float(np.nanmean(depth_res.data)) if depth_res.valid_pixels > 0 else math.nan
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=asset.checksum_sha256 or fname,
            provider=self.provider,
            product=req.product,
            variables=variables,
            units={k: v.units for k, v in variables.items()},
            spatial_metadata=SpatialMetadata(
                "raster",
                decoded.crs or "EPSG:4326",
                decoded.grid.bounds if decoded.grid else None,
                decoded.grid,
            ),
            temporal_metadata=temporal,
            quality_metadata=QualityMetadata(
                qa_policy="imerg_interval_coverage",
                valid_observation_fraction=valid_frac,
                excluded_count=excluded,
                exclusion_reasons=("missing or nodata precipitation rate",) if excluded else (),
            ),
            assets=(asset,),
            provenance=build_provenance(
                self.provider, req.product, ver, final_url, run_type=run_type
            ),
            extensions={
                "precip_variable": precip_key,
                "run_type": run_type,
                "interval_depth_mean_mm": None if math.isnan(mean_depth) else mean_depth,
            },
        )
