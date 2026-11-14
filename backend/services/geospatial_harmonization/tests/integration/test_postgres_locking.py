"""Live PostgreSQL FOR UPDATE SKIP LOCKED integration test (opt-in via GHS_TEST_POSTGRES_URL)."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, HarmonizationPlan
from geospatial_harmonization.infrastructure.database import (
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import SqlAlchemyJobRepository

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
