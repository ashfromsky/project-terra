"""Provider handler registry and default handler construction."""

from pathlib import Path

import httpx

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.handlers.generic import GenericHandler
from geospatial_harmonization.handlers.gpm_imerg import GPMIMERGHandler
from geospatial_harmonization.handlers.modis import MODISHandler
from geospatial_harmonization.handlers.nasa_power import NASAPowerHandler
from geospatial_harmonization.handlers.registry import HandlerRegistry
from geospatial_harmonization.handlers.smap import SMAPHandler
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry


def build_default_handler_registry(
    *,
    settings: Settings | None = None,
    reader_registry: ReaderRegistry | None = None,
    raw_dir: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HandlerRegistry:
    """Register all built-in provider handlers cleanly onto a fresh HandlerRegistry."""
    cfg = settings or get_settings()
    readers = reader_registry or build_default_reader_registry()
    registry = HandlerRegistry()
    registry.register(
        MODISHandler(settings=cfg, reader_registry=readers, raw_dir=raw_dir, transport=transport)
    )
    registry.register(
        GPMIMERGHandler(settings=cfg, reader_registry=readers, raw_dir=raw_dir, transport=transport)
    )
    registry.register(
        SMAPHandler(settings=cfg, reader_registry=readers, raw_dir=raw_dir, transport=transport)
    )
    registry.register(NASAPowerHandler(settings=cfg, raw_dir=raw_dir, transport=transport))
    registry.register(
        GenericHandler(settings=cfg, reader_registry=readers, raw_dir=raw_dir, transport=transport)
    )
    return registry


__all__ = [
    "GPMIMERGHandler",
    "GenericHandler",
    "HandlerRegistry",
    "MODISHandler",
    "NASAPowerHandler",
    "SMAPHandler",
    "build_default_handler_registry",
]
