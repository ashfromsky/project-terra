"""Live PostgreSQL FOR UPDATE SKIP LOCKED integration test (opt-in via GHS_TEST_POSTGRES_URL)."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from geospatial_harmonization.domain.exceptions import StorageBudgetExceededError
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, HarmonizationPlan
from geospatial_harmonization.domain.models.storage import StorageReservation
from geospatial_harmonization.infrastructure.database import (
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import SqlAlchemyJobRepository
from geospatial_harmonization.infrastructure.storage_ledger import SqlAlchemyStorageLedgerRepository

PG_URL = os.getenv("GHS_TEST_POSTGRES_URL")
SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not PG_URL, reason="Set GHS_TEST_POSTGRES_URL to run live PostgreSQL tests")
async def test_postgres_concurrent_workers_skip_locked_and_alembic() -> None:
    assert PG_URL is not None
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", PG_URL)
    command.upgrade(cfg, "head")

    engine = build_async_engine(PG_URL)
    try:
        repo = SqlAlchemyJobRepository(build_session_factory(engine))
        t0 = datetime.now(UTC)
        jobs = [
            HarmonizationJob(
                job_id=uuid4(),
                plan=HarmonizationPlan(
                    uuid4(), "generic", f"p{i}", {"url": "https://data.example.org/a.tif"}
                ),
                status="pending",
                created_at=t0 + timedelta(seconds=i),
                updated_at=t0 + timedelta(seconds=i),
            )
            for i in range(4)
        ]
        for job in jobs:
            await repo.create(job)

        claimed = await asyncio.gather(
            *(repo.claim_next_pending(f"w{i}", 60, t0 + timedelta(seconds=10)) for i in range(4))
        )
        claimed_ids = [c.job_id for c in claimed if c is not None]
        assert len(claimed_ids) == 4
        assert set(claimed_ids) == {j.job_id for j in jobs}
    finally:
        await engine.dispose()


@pytest.mark.skipif(not PG_URL, reason="Set GHS_TEST_POSTGRES_URL to run live PostgreSQL tests")
async def test_postgres_concurrent_quota_reservations_locking() -> None:
    assert PG_URL is not None
    engine = build_async_engine(PG_URL)
    try:
        ledger = SqlAlchemyStorageLedgerRepository(build_session_factory(engine))
        now = datetime.now(UTC)
        await ledger.ensure_ledger_initialized(now)
        metrics = await ledger.get_usage_metrics(now)
        effective_budget = metrics.total_stored_bytes + metrics.reserved_bytes + 2_000

        async def _try_reserve(idx: int) -> StorageReservation | None:
            res = StorageReservation(
                reservation_id=uuid4(),
                job_id=f"pg-lock-job-{idx}-{uuid4()}",
                zone="derived",
                operation="pg_concurrent_test",
                reserved_bytes=900,
                created_at=now,
                expires_at=now + timedelta(minutes=10),
                status="active",
            )
            try:
                return await ledger.reserve_capacity(
                    res,
                    budget_bytes=effective_budget,
                    hard_limit_threshold=1.0,
                    max_object_bytes=10_000,
                    max_job_output_bytes=10_000,
                    now=now,
                )
            except StorageBudgetExceededError:
                return None

        results = await asyncio.gather(*(_try_reserve(i) for i in range(4)))
        succeeded = [r for r in results if r is not None]
        assert len(succeeded) == 2
        for res in succeeded:
            await ledger.release_reservation(
                res.reservation_id, status="released", now=now, reason="test_cleanup"
            )
    finally:
        await engine.dispose()
