"""MODIS handler (MOD13Q1.061, MOD11A2.061) with Sinusoidal CRS and 8/16-day composites."""

import tempfile
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict
from pyproj import CRS

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
    safe_fetch_to_file,
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
        self._max_object_bytes = cfg.ghs_storage_max_object_bytes
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

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Download MODIS granule lazily via ReaderRegistry without warping or QA scaling."""
        req = parse_handler_payload(MODISPayload, payload)
        comp_days, cadence, template_specs = _PRODUCT_SPECS[req.product]
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        t0 = req.start_time.astimezone(UTC)
        url = req.granule_url or await discover_cmr_granule_url(
            self._cmr_url,
            req.product,
            t0,
            t0 + timedelta(days=comp_days),
            (".hdf", ".tif", ".tiff"),
            bbox=req.bbox,
            headers=headers,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_modis_"))
        path, asset, final_url = await safe_fetch_to_file(
            url,
            base_dir,
            fallback_filename=f"{req.product}.hdf",
            data_format=req.data_format,
            allowed_hosts=earthdata_hosts_for(self._cmr_url),
            headers=headers,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
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
