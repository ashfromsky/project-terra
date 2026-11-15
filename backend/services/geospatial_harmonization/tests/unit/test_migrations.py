"""Tests verifying Alembic upgrade, downgrade, table isolation, and SQLite startup sync."""

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from geospatial_harmonization.config.settings import Settings
from geospatial_harmonization.infrastructure.database import GhsBase, build_async_engine
from geospatial_harmonization.main import create_app
from geospatial_harmonization.worker.__main__ import build_worker_runtime

SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_alembic_upgrade_downgrade_cycle(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.db"
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")

    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        job_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(ghs_harmonization_jobs)").fetchall()
        }
        version_column = next(
            row
            for row in conn.execute("PRAGMA table_info(ghs_alembic_version)").fetchall()
            if row[1] == "version_num"
        )
    expected_tables = {
        "ghs_alembic_version",
        "ghs_datasets",
        "ghs_assets",
        "ghs_harmonization_jobs",
        "ghs_storage_ledger_state",
        "ghs_storage_objects",
        "ghs_storage_asset_refs",
        "ghs_storage_reservations",
        "ghs_storage_audit_events",
    }
    assert expected_tables <= tables
    assert version_column[2].upper() == "VARCHAR(255)"
    assert {"error_category", "next_retry_at", "progress_pct", "idempotency_key"} <= job_columns

    command.downgrade(cfg, "0002_storage_ledger_and_lifecycle")
    with sqlite3.connect(db_path) as conn:
        downgraded_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(ghs_harmonization_jobs)").fetchall()
        }
    assert not (
        {"error_category", "next_retry_at", "progress_pct", "idempotency_key"} & downgraded_cols
    )

    command.downgrade(cfg, "base")
    with sqlite3.connect(db_path) as conn:
        remaining = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert not (remaining & (expected_tables - {"ghs_alembic_version"}))
    assert "ghs_alembic_version" in remaining

    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        reupgraded_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(ghs_harmonization_jobs)").fetchall()
        }
    assert {"error_category", "next_retry_at", "progress_pct", "idempotency_key"} <= reupgraded_cols


async def test_worker_and_api_migrate_legacy_unversioned_0002_sqlite_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_0002.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    alembic_cfg = _make_alembic_config(db_url)
    await asyncio.to_thread(command.upgrade, alembic_cfg, "0002_storage_ledger_and_lifecycle")

    job_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()
    plan_json = json.dumps(
        {
            "plan_id": str(uuid4()),
            "provider": "unknown_provider",
            "product": "bad_product",
            "request_payload": {},
        }
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ghs_harmonization_jobs (
                id, provider, product, status, plan_json, attempt, max_attempts,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "unknown_provider",
                "bad_product",
                "pending",
                plan_json,
                0,
                1,
                now_iso,
                now_iso,
            ),
        )
        conn.execute("DROP TABLE ghs_alembic_version")
        conn.commit()

    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=db_url,
        local_storage_dir=tmp_path / "store",
    )
    engine, runner = await build_worker_runtime(settings)
    try:
        processed = await runner.drain()
        assert processed == 1
    finally:
        await engine.dispose()

    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        resp = await client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_category"] == "validation"

    with sqlite3.connect(db_path) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version_num FROM ghs_alembic_version").fetchall()
        }
    assert versions == {"0003_job_retry_and_idempotency"}


async def test_api_migrates_legacy_unversioned_0001_sqlite_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_0001.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    alembic_cfg = _make_alembic_config(db_url)
    await asyncio.to_thread(command.upgrade, alembic_cfg, "0001_initial_ghs_tables")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE ghs_alembic_version")
        conn.commit()

    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=db_url,
        local_storage_dir=tmp_path / "store",
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        usage = await client.get("/api/v1/storage/usage")
        assert usage.status_code == 200
        job_resp = await client.post(
            "/api/v1/jobs",
            json={
                "provider": "nasa_power",
                "product": "power_daily",
                "request_payload": {
                    "product": "power_daily",
                    "mode": "point",
                    "latitude": 50.0,
                    "longitude": 30.0,
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-02",
                    "parameters": ["PRECTOTCORR"],
                },
            },
        )
        assert job_resp.status_code == 202

    with sqlite3.connect(db_path) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version_num FROM ghs_alembic_version").fetchall()
        }
    assert versions == {"0003_job_retry_and_idempotency"}


async def test_concurrent_api_and_worker_startup_on_fresh_sqlite_db(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent.db"
    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_path}",
        local_storage_dir=tmp_path / "store",
    )

    async def _boot_api() -> None:
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            pass

    async def _boot_worker() -> None:
        engine, runner = await build_worker_runtime(settings)
        try:
            assert await runner.drain() == 0
        finally:
            await engine.dispose()

    await asyncio.gather(_boot_api(), _boot_worker())

    with sqlite3.connect(db_path) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version_num FROM ghs_alembic_version").fetchall()
        }
    assert versions == {"0003_job_retry_and_idempotency"}


async def test_worker_runtime_supports_in_memory_sqlite_and_already_full_create_all_db(
    tmp_path: Path,
) -> None:
    mem_settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        local_storage_dir=tmp_path / "mem_store",
    )
    mem_engine, mem_runner = await build_worker_runtime(mem_settings)
    try:
        assert await mem_runner.drain() == 0
    finally:
        await mem_engine.dispose()

    full_path = tmp_path / "full_create_all.db"
    full_url = f"sqlite+aiosqlite:///{full_path}"
    raw_engine = build_async_engine(full_url)
    try:
        async with raw_engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
    finally:
        await raw_engine.dispose()

    full_settings = Settings(
        _env_file=None,
        environment="development",
        database_url=full_url,
        local_storage_dir=tmp_path / "full_store",
    )
    full_engine, full_runner = await build_worker_runtime(full_settings)
    try:
        assert await full_runner.drain() == 0
    finally:
        await full_engine.dispose()

    with sqlite3.connect(full_path) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version_num FROM ghs_alembic_version").fetchall()
        }
    assert versions == {"0003_job_retry_and_idempotency"}


async def test_cross_process_concurrent_sqlite_schema_init(tmp_path: Path) -> None:
    db_path = tmp_path / "multiprocess.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    store_dir = tmp_path / "store"
    script = (
        "import asyncio\n"
        "from pathlib import Path\n"
        "from geospatial_harmonization.config.settings import Settings\n"
        "from geospatial_harmonization.worker.__main__ import build_worker_runtime\n"
        "async def main():\n"
        f"    cfg = Settings(_env_file=None, environment='development', database_url={db_url!r}, "
        f"local_storage_dir=Path({str(store_dir)!r}))\n"
        "    engine, runner = await build_worker_runtime(cfg)\n"
        "    try:\n"
        "        await runner.drain()\n"
        "    finally:\n"
        "        await engine.dispose()\n"
        "asyncio.run(main())\n"
    )
    procs = await asyncio.gather(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        ),
        asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        ),
    )
    outcomes = await asyncio.gather(*(proc.communicate() for proc in procs))
    for proc, (stdout, stderr) in zip(procs, outcomes, strict=True):
        assert proc.returncode == 0, f"stdout={stdout.decode()} stderr={stderr.decode()}"

    with sqlite3.connect(db_path) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version_num FROM ghs_alembic_version").fetchall()
        }
    assert versions == {"0003_job_retry_and_idempotency"}


async def test_corrupt_partial_unversioned_sqlite_db_raises_explicit_error(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE ghs_datasets (id VARCHAR(36) PRIMARY KEY)")
        conn.commit()

    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_path}",
        local_storage_dir=tmp_path / "store",
    )
    with pytest.raises(RuntimeError, match="partial GHS schema"):
        await build_worker_runtime(settings)
