"""MODIS handler (MOD13Q1.061, MOD11A2.061) with Sinusoidal CRS and 8/16-day composites."""

import json
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
from pyproj import CRS

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
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
    parse_handler_payload,
    safe_fetch_bytes,
    write_raw_asset,
)
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry

MODIS_SINUSOIDAL_WKT = CRS.from_proj4(
    "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
).to_wkt()

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
_NASA_HOSTS = ("*.nasa.gov", "*.earthdata.nasa.gov", "*.earthdatacloud.nasa.gov")


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
        self._cmr_url = cfg.cmr_base_url.rstrip("/")
        self._token = cfg.earthdata_token.get_secret_value() if cfg.earthdata_token else None
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._readers = reader_registry or build_default_reader_registry()
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "modis"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("MOD13Q1.061", "MOD11A2.061")

    def _allowed_hosts(self) -> tuple[str, ...]:
        cmr_host = (urlparse(self._cmr_url).hostname or "").lower()
        return (*_NASA_HOSTS, cmr_host) if cmr_host else _NASA_HOSTS

    async def _resolve_granule_url(self, req: MODISPayload, headers: Mapping[str, str]) -> str:
        if req.granule_url:
            return req.granule_url
        short_name, version = req.product.split(".", 1)
        t0 = req.start_time.astimezone(UTC)
        days = _PRODUCT_SPECS[req.product][0]
        params = {
            "short_name": short_name,
            "version": version,
            "temporal": f"{t0.isoformat()},{(t0 + timedelta(days=days)).isoformat()}",
            "page_size": "1",
        }
        if req.bbox is not None:
            params["bounding_box"] = ",".join(str(v) for v in req.bbox)
        raw, _, _ = await safe_fetch_bytes(
            f"{self._cmr_url}/granules.json",
            allowed_hosts=self._allowed_hosts(),
            headers=headers,
            params=params,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        doc = json.loads(raw.decode("utf-8"))
        entries = doc.get("feed", {}).get("entry", []) if isinstance(doc, Mapping) else []
        for entry in entries:
            for link in entry.get("links", []) if isinstance(entry, Mapping) else []:
                href = link.get("href", "") if isinstance(link, Mapping) else ""
                if href.startswith("https://") and href.lower().endswith((".hdf", ".tif", ".tiff")):
                    return str(href)
        raise IncompatibleDatasetError(f"No CMR granule download URL found for '{req.product}'")

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Download MODIS granule lazily via ReaderRegistry without warping or QA scaling."""
        req = parse_handler_payload(MODISPayload, payload)
        comp_days, cadence, template_specs = _PRODUCT_SPECS[req.product]
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        url = await self._resolve_granule_url(req, headers)
        raw, final_url, media = await safe_fetch_bytes(
            url,
            allowed_hosts=self._allowed_hosts(),
            headers=headers,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_modis_"))
        fname = Path(urlparse(final_url).path).name or f"{req.product}.hdf"
        path, asset = write_raw_asset(base_dir, fname, raw, req.data_format, media)
        decoded = self._readers.read(asset, path, variables=req.variables)

        variables: dict[str, VariableSpec] = {}
        for name, dec_spec in decoded.variables.items():
            known = template_specs.get(name)
            if known is None:
                variables[name] = dec_spec
            elif known.semantics in ("qa_flag", "categorical"):
                variables[name] = replace(
                    known,
                    dimensions=dec_spec.dimensions,
                    dtype=dec_spec.dtype,
                    nodata=dec_spec.nodata if dec_spec.nodata is not None else known.nodata,
                    grid=dec_spec.grid,
                )
            else:
                variables[name] = replace(
                    known,
                    dimensions=dec_spec.dimensions,
                    dtype=dec_spec.dtype,
                    nodata=dec_spec.nodata if dec_spec.nodata is not None else known.nodata,
                    grid=dec_spec.grid,
                )

        first_spec = next(iter(variables.values()))
        first_arr = np.asarray(decoded.arrays[first_spec.name])
        valid_frac = (
            float(np.count_nonzero(first_arr != first_spec.nodata) / first_arr.size)
            if first_spec.nodata is not None and first_arr.size > 0
            else None
        )
        t0 = req.start_time.astimezone(UTC)
        temporal = TemporalSpec(
            t0, t0 + timedelta(days=comp_days), cadence, "composite", composite_days=comp_days
        )
        crs = decoded.crs or MODIS_SINUSOIDAL_WKT
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
            temporal_metadata=temporal,
            quality_metadata=QualityMetadata(
                "modis_composite_qa_separated",
                valid_observation_fraction=valid_frac,
                flags_applied=tuple(k for k, v in variables.items() if v.semantics == "qa_flag"),
            ),
            assets=(asset,),
            provenance=build_provenance(self.provider, req.product, "061", final_url),
            extensions={"composite_days": comp_days, "authalic_sphere_radius_m": 6371007.181},
        )
