"""Standalone CLI entrypoint (`python -m geospatial_harmonization.worker`)."""

import asyncio
import logging
import signal
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyJobRepository,
)
from geospatial_harmonization.infrastructure.storage import build_storage_port
from geospatial_harmonization.readers import build_default_reader_registry
from geospatial_harmonization.worker.runner import WorkerRunner

logger = logging.getLogger("geospatial_harmonization.worker")


async def build_worker_runtime(
    settings: Settings | None = None,
) -> tuple[AsyncEngine, WorkerRunner]:
    """Wire database, storage, handlers, and WorkerRunner for process execution."""
    cfg = settings or get_settings()
    engine = build_async_engine(cfg.database_url, echo=cfg.database_echo)
    if cfg.environment != "production" and cfg.database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
    sessions = build_session_factory(engine)
    readers = build_default_reader_registry()
    handlers = build_default_handler_registry(settings=cfg, reader_registry=readers)
    storage = build_storage_port(cfg)
    service = HarmonizationService(
        handlers=handlers,
        storage=storage,
        datasets=SqlAlchemyDatasetRepository(sessions),
        readers=readers,
        max_grid_pixels=cfg.max_grid_pixels,
    )
    runner = WorkerRunner(
        service=service,
        jobs=SqlAlchemyJobRepository(sessions),
        lease_seconds=cfg.worker_lease_seconds,
        poll_interval_seconds=cfg.worker_poll_interval_seconds,
    )
    return engine, runner


async def _run_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    engine, runner = await build_worker_runtime()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    logger.info("Starting GHS worker loop")
    try:
        await runner.run_until_stopped(stop_event)
    finally:
        await engine.dispose()
        logger.info("Stopped GHS worker loop")


if __name__ == "__main__":
    asyncio.run(_run_worker())
