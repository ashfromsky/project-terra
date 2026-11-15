"""Object storage abstraction and local/S3(Cloudflare R2) adapters for TERRA Core."""

from terra.infrastructure.object_storage.store import (
    LocalCoreObjectStore,
    ObjectStoragePort,
    S3CoreObjectStore,
    StoredObjectDescriptor,
    build_core_object_storage,
    normalize_core_object_key,
)

__all__ = [
    "LocalCoreObjectStore",
    "ObjectStoragePort",
    "S3CoreObjectStore",
    "StoredObjectDescriptor",
    "build_core_object_storage",
    "normalize_core_object_key",
]
