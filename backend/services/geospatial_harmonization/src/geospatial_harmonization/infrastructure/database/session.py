"""Async SQLAlchemy engine, session factory, and connectivity health check."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_async_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create a configured SQLAlchemy AsyncEngine for PostgreSQL or SQLite."""
    is_sqlite = database_url.startswith("sqlite")
    kwargs: dict[str, object] = {"echo": echo}
    if not is_sqlite:
        kwargs["pool_pre_ping"] = True
    return create_async_engine(database_url, **kwargs)


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
