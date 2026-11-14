"""Async Alembic environment isolated to GHS tables via ghs_alembic_version."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from geospatial_harmonization.config.settings import get_settings
from geospatial_harmonization.infrastructure.database.models import GhsBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = GhsBase.metadata
VERSION_TABLE = "ghs_alembic_version"


def _resolve_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return configured if configured else get_settings().database_url


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
        async with connectable.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
