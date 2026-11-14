"""SQLAlchemy declarative base and naming convention for GHS-owned tables."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

GHS_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GhsBase(DeclarativeBase):
    """Base declarative class isolated to Geospatial Harmonization Service tables."""

    metadata = MetaData(naming_convention=GHS_NAMING_CONVENTION)
