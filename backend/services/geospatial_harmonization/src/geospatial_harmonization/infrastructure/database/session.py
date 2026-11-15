"""Async SQLAlchemy engine, session factory, and connectivity health check."""

from pathlib import Path
from typing import Protocol

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class _DbapiCursor(Protocol):
    def execute(self, sql: str) -> object: ...
    def close(self) -> object: ...


class _DbapiConnection(Protocol):
    def cursor(self) -> _DbapiCursor: ...


def is_sqlite_url(database_url: str) -> bool:
    """Return True when the SQLAlchemy URL targets SQLite."""
    return make_url(database_url).get_backend_name() == "sqlite"


def sqlite_file_path(database_url: str) -> Path | None:
    """Return the resolved filesystem path for file-backed SQLite URLs, or None."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    db = url.database
    if db in (None, "", ":memory:") or url.query.get("mode") == "memory":
        return None
    return Path(db).resolve()


def build_async_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create a configured SQLAlchemy AsyncEngine for PostgreSQL or SQLite."""
    is_sqlite = is_sqlite_url(database_url)
    kwargs: dict[str, object] = {"echo": echo}
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30.0}
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_async_engine(database_url, **kwargs)
    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _configure_sqlite_connection(
            dbapi_connection: _DbapiConnection, _connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout = 30000")
            finally:
                cursor.close()

    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an AsyncSession factory with expire_on_commit disabled."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database_health(engine: AsyncEngine) -> bool:
    """Verify database connectivity by executing a lightweight SELECT 1 query."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
