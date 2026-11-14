"""Shared FastAPI dependencies for the API layer."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from terra.config import Settings, get_settings
from terra.infrastructure.database import DatabaseManager


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running app instance."""
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def get_database_manager(request: Request) -> DatabaseManager:
    """Return the DatabaseManager bound to the running app lifespan."""
    return request.app.state.db


async def get_db_session(
    db: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped async SQLAlchemy session."""
    async with db.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseManagerDep = Annotated[DatabaseManager, Depends(get_database_manager)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
