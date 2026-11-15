"""Async Alembic environment isolated to GHS tables via ghs_alembic_version."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Column, Connection, MetaData, String, Table, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from geospatial_harmonization.config.settings import get_settings
from geospatial_harmonization.infrastructure.database.models import GhsBase

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = GhsBase.metadata
VERSION_TABLE = "ghs_alembic_version"
# Alembic hardcodes String(32) for version_num, but GHS revision identifiers are longer
# (for example "0002_storage_ledger_and_lifecycle"), which PostgreSQL rejects.
VERSION_NUM_LENGTH = 255


def _resolve_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return configured if configured else get_settings().database_url


def _widen_version_num(connection: Connection) -> None:
    """Widen a version table created earlier with Alembic's default column width."""
    if connection.dialect.name != "postgresql":
        return
    current_length = connection.execute(
        text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name "
            "AND column_name = 'version_num'"
        ),
        {"table_name": VERSION_TABLE},
    ).scalar_one_or_none()
    if current_length is not None and current_length < VERSION_NUM_LENGTH:
        connection.execute(
            text(
                f"ALTER TABLE {VERSION_TABLE} ALTER COLUMN version_num "
                f"TYPE VARCHAR({VERSION_NUM_LENGTH})"
            )
        )


def _ensure_version_table(connection: Connection) -> None:
    """Create the version table with a revision-id column wide enough for GHS ids."""
    Table(
        VERSION_TABLE,
        MetaData(),
        Column("version_num", String(VERSION_NUM_LENGTH), primary_key=True),
    ).create(connection, checkfirst=True)
    _widen_version_num(connection)


def _ensure_version_table_before_migrations(connection: Connection) -> None:
    """Prepare the version table without leaving Alembic inside an external transaction."""
    started_transaction = not connection.in_transaction()
    _ensure_version_table(connection)
    if started_transaction:
        connection.commit()


def run_migrations_offline() -> None:
    """Run Alembic migrations in offline SQL generation mode."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table=VERSION_TABLE,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run Alembic migrations against an async SQLAlchemy engine."""
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.begin() as version_connection:
            await version_connection.run_sync(_ensure_version_table)
        async with connectable.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    provided_connection = config.attributes.get("connection")
    if isinstance(provided_connection, Connection):
        _ensure_version_table_before_migrations(provided_connection)
        _run_sync_migrations(provided_connection)
    else:
        asyncio.run(run_migrations_online())
