"""Shared FastAPI dependencies for the API layer."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from terra.config import Settings, get_settings
from terra.infrastructure.database import DatabaseManager
from terra.infrastructure.object_storage import ObjectStoragePort, build_core_object_storage


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running app instance."""
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def get_database_manager(request: Request) -> DatabaseManager:
    """Return the DatabaseManager bound to the running app lifespan."""
    return request.app.state.db


def get_object_storage(request: Request) -> ObjectStoragePort:
    """Return the ObjectStoragePort bound to the running app instance."""
    store: ObjectStoragePort | None = getattr(request.app.state, "object_storage", None)
    if store is not None:
        return store
    store = build_core_object_storage(get_app_settings(request))
    request.app.state.object_storage = store
    return store


async def get_db_session(
    db: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped async SQLAlchemy session."""
    async with db.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseManagerDep = Annotated[DatabaseManager, Depends(get_database_manager)]
ObjectStorageDep = Annotated[ObjectStoragePort, Depends(get_object_storage)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
