"""Database infrastructure: declarative base, ORM models, JSON codecs, and async sessions."""

from geospatial_harmonization.infrastructure.database.base import GhsBase
from geospatial_harmonization.infrastructure.database.codec import (
    decode_dataset,
    decode_plan,
    encode_dataset,
    encode_plan,
    ensure_utc,
)
from geospatial_harmonization.infrastructure.database.models import (
    GhsAssetModel,
    GhsDatasetModel,
    GhsHarmonizationJobModel,
    GhsStorageAssetRefModel,
    GhsStorageAuditEventModel,
    GhsStorageLedgerStateModel,
    GhsStorageObjectModel,
    GhsStorageReservationModel,
)
from geospatial_harmonization.infrastructure.database.session import (
    build_async_engine,
    build_session_factory,
    check_database_health,
)

__all__ = [
    "GhsAssetModel",
    "GhsBase",
    "GhsDatasetModel",
    "GhsHarmonizationJobModel",
    "GhsStorageAssetRefModel",
    "GhsStorageAuditEventModel",
    "GhsStorageLedgerStateModel",
    "GhsStorageObjectModel",
    "GhsStorageReservationModel",
    "build_async_engine",
    "build_session_factory",
    "check_database_health",
    "decode_dataset",
    "decode_plan",
    "encode_dataset",
    "encode_plan",
    "ensure_utc",
]
