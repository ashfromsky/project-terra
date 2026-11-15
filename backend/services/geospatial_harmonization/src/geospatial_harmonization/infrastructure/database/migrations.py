"""SQLite schema migration and legacy unversioned database reconciliation for GHS."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import ModuleType
from weakref import WeakKeyDictionary

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Inspector, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from geospatial_harmonization.infrastructure.database.session import sqlite_file_path

_fcntl: ModuleType | None
try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

logger = logging.getLogger("geospatial_harmonization.migrations")

_VERSION_TABLE = "ghs_alembic_version"
_REV_0001 = "0001_initial_ghs_tables"
_REV_0002 = "0002_storage_ledger_and_lifecycle"
_REV_0003 = "0003_job_retry_and_idempotency"

_V0001_TABLES = frozenset({"ghs_datasets", "ghs_assets", "ghs_harmonization_jobs"})
_V0002_TABLES = frozenset(
    {
        "ghs_storage_ledger_state",
        "ghs_storage_objects",
        "ghs_storage_asset_refs",
        "ghs_storage_reservations",
        "ghs_storage_audit_events",
    }
)
_ALL_GHS_TABLES = _V0001_TABLES | _V0002_TABLES
_V0003_JOB_COLUMNS = frozenset(
    {"error_category", "next_retry_at", "progress_pct", "idempotency_key"}
)
_V0003_JOB_INDEXES = frozenset({"ix_ghs_jobs_status_next_retry_at", "ix_ghs_jobs_idempotency_key"})

_MIGRATION_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    WeakKeyDictionary()
)


def _get_intra_process_lock(lock_key: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    per_loop = _MIGRATION_LOCKS.setdefault(loop, {})
    lock = per_loop.get(lock_key)
    if lock is None:
        lock = asyncio.Lock()
        per_loop[lock_key] = lock
    return lock


def _acquire_file_lock(lock_path: Path) -> int | None:
    if _fcntl is None or not lock_path.parent.exists():
        return None
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _fcntl.flock(fd, _fcntl.LOCK_EX)
    except Exception:
        os.close(fd)
        raise
    return fd


def _release_file_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        if _fcntl is not None:
            with suppress(OSError):
                _fcntl.flock(fd, _fcntl.LOCK_UN)
    finally:
        os.close(fd)


@asynccontextmanager
async def _sqlite_migration_lock(db_path: Path | None, engine: AsyncEngine) -> AsyncIterator[None]:
    lock_key = str(db_path) if db_path is not None else f"memory:{id(engine)}"
    intra_lock = _get_intra_process_lock(lock_key)
    async with intra_lock:
        fd: int | None = None
        if db_path is not None:
            lock_path = db_path.parent / f"{db_path.name}-migrate.lock"
            fd = await asyncio.to_thread(_acquire_file_lock, lock_path)
        try:
            yield
        finally:
            if fd is not None:
                _release_file_lock(fd)


def _resolve_alembic_paths() -> tuple[Path, Path]:
    roots = [
        *Path(__file__).resolve().parents,
        Path.cwd(),
        *Path.cwd().parents,
    ]
    seen: set[Path] = set()
    for candidate in roots:
        if candidate in seen:
            continue
        seen.add(candidate)
        ini_path = candidate / "alembic.ini"
        script_dir = candidate / "alembic"
        if ini_path.is_file() and script_dir.is_dir():
            return ini_path, script_dir
    raise FileNotFoundError("Could not locate GHS alembic.ini and alembic/ migrations directory")


def _build_alembic_config(database_url: str) -> Config:
    ini_path, script_dir = _resolve_alembic_paths()
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(script_dir))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


def _detect_legacy_unversioned_revision(inspector: Inspector, tables: set[str]) -> str | None:
    present = tables & _ALL_GHS_TABLES
    if not present:
        return None
    if not (tables >= _V0001_TABLES):
        raise RuntimeError(
            f"Unversioned SQLite database has partial GHS schema ({sorted(present)}) "
            f"without {_VERSION_TABLE}; recreate the local database or apply migrations cleanly."
        )

    has_all_0002 = tables >= _V0002_TABLES
    has_any_0002 = bool(_V0002_TABLES & tables)
    if has_any_0002 and not has_all_0002:
        raise RuntimeError(
            f"Unversioned SQLite database has partial storage schema ({sorted(present)}) "
            f"without {_VERSION_TABLE}; recreate the local database or repair missing tables."
        )

    job_cols = {col["name"] for col in inspector.get_columns("ghs_harmonization_jobs")}
    job_indexes = {
        idx["name"] for idx in inspector.get_indexes("ghs_harmonization_jobs") if idx.get("name")
    }
    has_all_0003 = (job_cols >= _V0003_JOB_COLUMNS) and (job_indexes >= _V0003_JOB_INDEXES)
    has_any_0003 = bool(_V0003_JOB_COLUMNS & job_cols)
    if has_any_0003 and not has_all_0003:
        raise RuntimeError(
            "Unversioned SQLite database has partial job retry columns/indexes on "
            "ghs_harmonization_jobs without ghs_alembic_version."
        )
    if has_all_0003 and not has_all_0002:
        raise RuntimeError(
            "Unversioned SQLite database has job retry columns without storage ledger tables."
        )

    if has_all_0002 and has_all_0003:
        return _REV_0003
    if has_all_0002:
        return _REV_0002
    return _REV_0001


def _apply_sqlite_migrations_sync(sync_conn: Connection, cfg: Config, *, enable_wal: bool) -> None:
    if enable_wal:
        sync_conn.execution_options(isolation_level="AUTOCOMMIT").exec_driver_sql(
            "PRAGMA journal_mode = WAL"
        )

    script = ScriptDirectory.from_config(cfg)
    heads = set(script.get_heads())
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())

    current_versions: set[str] = set()
    if _VERSION_TABLE in tables:
        rows = sync_conn.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}")).fetchall()
        current_versions = {str(row[0]) for row in rows if row[0]}

    if current_versions == heads:
        if sync_conn.in_transaction():
            sync_conn.rollback()
        return

    stamp_revision: str | None = None
    if not current_versions:
        stamp_revision = _detect_legacy_unversioned_revision(inspector, tables)

    if sync_conn.in_transaction():
        sync_conn.rollback()

    cfg.attributes["connection"] = sync_conn
    if stamp_revision is not None:
        logger.info("Stamping legacy unversioned GHS SQLite database at %s", stamp_revision)
        command.stamp(cfg, stamp_revision)
        if sync_conn.in_transaction():
            sync_conn.commit()
        if stamp_revision in heads:
            return

    command.upgrade(cfg, "head")
    if sync_conn.in_transaction():
        sync_conn.commit()


async def ensure_sqlite_schema(engine: AsyncEngine, database_url: str) -> None:
    """Apply pending Alembic migrations to a non-production SQLite database safely."""
    db_path = sqlite_file_path(database_url)
    cfg = _build_alembic_config(database_url)
    async with _sqlite_migration_lock(db_path, engine), engine.connect() as conn:
        await conn.run_sync(_apply_sqlite_migrations_sync, cfg, enable_wal=db_path is not None)
