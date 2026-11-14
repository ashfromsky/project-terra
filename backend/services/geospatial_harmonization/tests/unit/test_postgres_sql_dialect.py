"""Tests verifying PostgreSQL dialect SQL compilation and worker runtime assembly."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.infrastructure.database import (
    GhsHarmonizationJobModel,
    GhsStorageAssetRefModel,
    GhsStorageLedgerStateModel,
)
from geospatial_harmonization.infrastructure.repositories import build_claim_statement
from geospatial_harmonization.infrastructure.storage_ledger import build_ledger_lock_statement
from geospatial_harmonization.worker.__main__ import build_worker_runtime


def test_postgres_dialect_renders_skip_locked_and_jsonb() -> None:
    stmt = build_claim_statement(datetime(2026, 7, 1, tzinfo=UTC), skip_locked=True)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in compiled

    lock_stmt = build_ledger_lock_statement(for_update=True)
    assert "FOR UPDATE" in str(lock_stmt.compile(dialect=postgresql.dialect()))

    ddl = str(CreateTable(GhsHarmonizationJobModel.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" in ddl
    ref_ddl = str(
        CreateTable(GhsStorageAssetRefModel.__table__).compile(dialect=postgresql.dialect())
    )
    assert "JSONB" in ref_ddl
    ledger_ddl = str(
        CreateTable(GhsStorageLedgerStateModel.__table__).compile(dialect=postgresql.dialect())
    )
    assert "ghs_storage_ledger_state" in ledger_ddl


async def test_build_worker_runtime_initializes_and_drains(tmp_path: Path) -> None:
    cfg = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}",
        local_storage_dir=tmp_path / "store",
    )
    engine, runner = await build_worker_runtime(cfg)
    try:
        assert await runner.drain() == 0
    finally:
        await engine.dispose()
