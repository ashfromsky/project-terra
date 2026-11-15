"""SSRF-guarded GenericHandler for explicitly allowlisted declarative endpoints."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
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
    safe_fetch_to_file,
)
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.storage.scratch import run_with_owned_base_dir


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
        self._settings = cfg
        self._timeout = cfg.http_timeout_seconds
        self._max_retries = cfg.http_max_retries
        self._max_object_bytes = cfg.ghs_storage_max_object_bytes
        self._chunk_bytes = cfg.ghs_storage_stream_chunk_bytes
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
        return await run_with_owned_base_dir(
            lambda base_dir: self._handle_payload(payload, base_dir),
            settings=self._settings,
            prefix="ghs_generic_",
            raw_dir=self._raw_dir,
        )

    async def _handle_payload(
        self, payload: Mapping[str, object], base_dir: Path
    ) -> SpatialDataset:
        """Fetch an allowlisted URL into ``base_dir`` and decode it into a SpatialDataset."""
        req = parse_handler_payload(GenericPayload, payload)
        if not self._allowed_hosts:
            raise IncompatibleDatasetError(
                "GenericHandler is disabled because generic_handler_allowed_hosts is empty"
            )
        path, asset, final_url = await safe_fetch_to_file(
            req.url,
            base_dir,
            data_format=req.data_format,
            allowed_hosts=self._allowed_hosts,
            timeout=self._timeout,
            max_retries=self._max_retries,
            transport=self._transport,
            max_bytes=self._max_object_bytes,
            chunk_bytes=self._chunk_bytes,
        )
        fname = path.name
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
