"""Tests verifying Alembic upgrade, downgrade, and table isolation."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

SERVICE_ROOT = Path(__file__).resolve().parents[2]


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
