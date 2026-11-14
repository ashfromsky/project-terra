"""Shared FastAPI dependencies for the API layer."""

from typing import Annotated

from fastapi import Depends

from terra.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
