"""Zarr v2/v3 AssetReader using lazy group traversal without inventing CRS."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import zarr

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
)
from geospatial_harmonization.readers._helpers import to_attr_dict
from geospatial_harmonization.readers._nd_container import NdVarEntry, decode_nd_container
from geospatial_harmonization.readers.registry import AssetDecodeError


def _zarr_dims(arr: object, ndim: int, attrs: dict[str, object]) -> tuple[str, ...]:
    meta = getattr(arr, "metadata", None)
    raw = getattr(meta, "dimension_names", None) or attrs.get("_ARRAY_DIMENSIONS")
    if isinstance(raw, (list, tuple)) and len(raw) == ndim:
        return tuple(str(d or f"dim_{i}") for i, d in enumerate(raw))
    return tuple(f"dim_{i}" for i in range(ndim))


class _SliceReadable(Protocol):
    def __getitem__(self, item: slice, /) -> object: ...


def _zarr_reader(arr: _SliceReadable) -> Callable[[], object]:
    def _read() -> object:
        return arr[:]

    return _read


def _collect_entries(group: zarr.Group, prefix: str = "") -> list[tuple[str, NdVarEntry]]:
    items: list[tuple[str, NdVarEntry]] = []
    for name, member in group.members():
        full = f"{prefix}/{name}" if prefix else str(name)
        if isinstance(member, zarr.Array):
            attrs = to_attr_dict(member.attrs.items())
            ndim = int(member.ndim)
            items.append(
                (
                    full,
                    NdVarEntry(
                        full,
                        _zarr_dims(member, ndim, attrs),
                        ndim,
                        int(member.size),
                        str(member.dtype.kind),
                        attrs,
                        _zarr_reader(member),
                    ),
                )
            )
        elif isinstance(member, zarr.Group):
            items.extend(_collect_entries(member, full))
    return items


class ZarrReader:
    """Lazy decoder for Zarr v3 and Zarr v2 directory stores."""

    @property
    def data_format(self) -> DataFormat:
        return "zarr"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if not header:
            return asset.data_format in ("zarr", "unknown") or ".zarr" in asset.uri.lower()
        return header.startswith(b"PK\x03\x04") and ".zarr" in asset.uri.lower()

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            root = zarr.open_group(path, mode="r")
            root_attrs = to_attr_dict(root.attrs.items())
            entries = dict(_collect_entries(root))
            return decode_nd_container(asset, "zarr", entries, root_attrs, variables)
        except Exception as exc:
            if isinstance(exc, AssetDecodeError):
                raise
            raise AssetDecodeError(f"Failed to decode Zarr '{path.name}': {exc}") from exc
