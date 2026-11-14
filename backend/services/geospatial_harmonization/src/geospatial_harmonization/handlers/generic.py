"""SSRF-guarded GenericHandler for explicitly allowlisted declarative endpoints."""

import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    DataFormat,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
)
from geospatial_harmonization.domain.models.temporal import TemporalSemantics, TemporalSpec
from geospatial_harmonization.handlers.base import (
    build_provenance,
    parse_handler_payload,
    safe_fetch_bytes,
    write_raw_asset,
)
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry


class GenericPayload(BaseModel):
    """Input schema for GenericHandler declarative dataset ingestion."""

    model_config = ConfigDict(extra="forbid")

    url: str
    product: str = "generic_dataset"
    source_id: str | None = None
    data_format: DataFormat = "unknown"
    variables: tuple[str, ...] | None = None
    cadence: str = "irregular"
    temporal_semantics: TemporalSemantics = "instantaneous"
    start: datetime | None = None
    end: datetime | None = None


class GenericHandler:
    """Allowlisted, SSRF-guarded fallback handler delegating decoding to ReaderRegistry."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        allowed_hosts: Sequence[str] | None = None,
        reader_registry: ReaderRegistry | None = None,
        raw_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = settings or get_settings()
        hosts = (
            tuple(allowed_hosts)
            if allowed_hosts is not None
            else tuple(cfg.generic_handler_allowed_hosts)
        )
        self._allowed_hosts = hosts
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._readers = reader_registry or build_default_reader_registry()
        self._raw_dir = raw_dir
        self._transport = transport

    @property
    def provider(self) -> str:
        return "generic"

    @property
    def supported_products(self) -> tuple[str, ...]:
        return ("*",)

    async def handle_payload(self, payload: Mapping[str, object]) -> SpatialDataset:
        """Fetch an allowlisted URL safely and decode into a canonical SpatialDataset."""
        req = parse_handler_payload(GenericPayload, payload)
        if not self._allowed_hosts:
            raise IncompatibleDatasetError(
                "GenericHandler is disabled because generic_handler_allowed_hosts is empty"
            )
        raw, final_url, media = await safe_fetch_bytes(
            req.url,
            allowed_hosts=self._allowed_hosts,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
        )
        base_dir = self._raw_dir or Path(tempfile.mkdtemp(prefix="ghs_generic_"))
        fname = Path(urlparse(final_url).path).name or "generic_asset"
        path, asset = write_raw_asset(base_dir, fname, raw, req.data_format, media)
        decoded = self._readers.read(asset, path, variables=req.variables)
        if not decoded.variables:
            raise IncompatibleDatasetError("Decoded generic asset exposed zero variables")

        now = datetime.now(UTC)
        t_start = req.start or (decoded.temporal.start if decoded.temporal else now)
        t_end = req.end or (decoded.temporal.end if decoded.temporal else t_start)
        temporal = decoded.temporal or TemporalSpec(
            t_start, t_end, req.cadence, req.temporal_semantics
        )
        spatial = SpatialMetadata(
            representation="raster" if decoded.grid is not None else "vector",
            crs=decoded.crs,
            bounds=decoded.grid.bounds if decoded.grid is not None else None,
            grid=decoded.grid,
        )
        return SpatialDataset(
            dataset_id=uuid4(),
            source_id=req.source_id or asset.checksum_sha256 or fname,
            provider=self.provider,
            product=req.product,
            variables=decoded.variables,
            units={name: spec.units for name, spec in decoded.variables.items()},
            spatial_metadata=spatial,
            temporal_metadata=temporal,
            quality_metadata=QualityMetadata("raw"),
            assets=(asset,),
            provenance=build_provenance(self.provider, req.product, "1.0", final_url),
        )
