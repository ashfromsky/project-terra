"""Standalone CLI entrypoint (`python -m geospatial_harmonization.worker`)."""

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.handlers import build_default_handler_registry
from geospatial_harmonization.infrastructure.database import (
    build_async_engine,
    build_session_factory,
    ensure_sqlite_schema,
    is_sqlite_url,
)
from geospatial_harmonization.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyJobRepository,
)
from geospatial_harmonization.infrastructure.storage import build_storage_port
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository
from geospatial_harmonization.readers import build_default_reader_registry
from geospatial_harmonization.storage.compression import DataCompressionManager
from geospatial_harmonization.storage.dedup import ContentDeduplicationService
from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
from geospatial_harmonization.storage.quota import StorageQuotaManager
from geospatial_harmonization.storage.zones import StorageZoneManager
from geospatial_harmonization.worker.runner import WorkerRunner

logger = logging.getLogger("geospatial_harmonization.worker")


async def build_worker_runtime(
    settings: Settings | None = None,
) -> tuple[AsyncEngine, WorkerRunner]:
    """Wire database, storage, quota/lifecycle managers, handlers, and WorkerRunner."""
    cfg = settings or get_settings()
    engine = build_async_engine(cfg.database_url, echo=cfg.database_echo)
    try:
        if cfg.environment != "production" and is_sqlite_url(cfg.database_url):
            await ensure_sqlite_schema(engine, cfg.database_url)
        sessions = build_session_factory(engine)
        readers = build_default_reader_registry()
        handlers = build_default_handler_registry(settings=cfg, reader_registry=readers)
        storage = build_storage_port(cfg)
        ledger = SqlAlchemyStorageLedgerRepository(sessions)
        await ledger.ensure_ledger_initialized(datetime.now(UTC))
    except Exception:
        await engine.dispose()
        raise
    zones = StorageZoneManager(cfg)
    quota = StorageQuotaManager(ledger, storage, cfg)
    dedup = ContentDeduplicationService(storage, ledger, zones, cfg)
    lifecycle = StorageLifecycleManager(storage, ledger, zones, cfg)
    compression = DataCompressionManager(cfg)
    service = HarmonizationService(
        handlers=handlers,
        storage=storage,
        datasets=SqlAlchemyDatasetRepository(sessions),
        readers=readers,
        max_grid_pixels=cfg.max_grid_pixels,
        settings=cfg,
        ledger=ledger,
        zones=zones,
        quota=quota,
        dedup=dedup,
        lifecycle=lifecycle,
        compression=compression,
    )
    maint_interval = max(
        30.0,
        float(
            min(
                cfg.ghs_storage_reservation_ttl_seconds,
                cfg.ghs_storage_intermediate_retention_seconds,
            )
        )
        / 2.0,
    )
    runner = WorkerRunner(
        service=service,
        jobs=SqlAlchemyJobRepository(sessions),
        lease_seconds=cfg.worker_lease_seconds,
        poll_interval_seconds=cfg.worker_poll_interval_seconds,
        retry_backoff_seconds=cfg.http_retry_backoff_seconds,
        max_concurrency=cfg.ghs_storage_max_worker_concurrency,
        maintenance_interval_seconds=maint_interval,
        quota=quota,
        lifecycle=lifecycle,
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
