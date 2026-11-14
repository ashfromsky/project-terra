"""HDF5 AssetReader supporting grouped scientific datasets and HDF-EOS5 dimensions."""

from collections.abc import Callable
from pathlib import Path

import h5py

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
)
from geospatial_harmonization.readers._helpers import to_attr_dict
from geospatial_harmonization.readers._nd_container import NdVarEntry, decode_nd_container
from geospatial_harmonization.readers.registry import AssetDecodeError

_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


def _dim_names(ds: h5py.Dataset, attrs: dict[str, object]) -> tuple[str, ...]:
    if ds.ndim == 0:
        return ()
    if "DimensionNames" in attrs:
        parts = tuple(p.strip() for p in str(attrs["DimensionNames"]).split(",") if p.strip())
        if len(parts) == ds.ndim:
            return parts
    return tuple(ds.dims[i].label or f"dim_{i}" for i in range(ds.ndim))


def _h5_reader(ds: h5py.Dataset) -> Callable[[], object]:
    def _read() -> object:
        return ds[()] if ds.ndim == 0 else ds[...]

    return _read


def _collect_entries(group: h5py.Group, prefix: str = "") -> list[tuple[str, NdVarEntry]]:
    items: list[tuple[str, NdVarEntry]] = []
    for key, member in group.items():
        full = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(member, h5py.Dataset):
            attrs = to_attr_dict(member.attrs.items())
            entry = NdVarEntry(
                name=full,
                dimensions=_dim_names(member, attrs),
                ndim=int(member.ndim),
                size=int(member.size),
                dtype_kind=str(member.dtype.kind),
                attributes=attrs,
                read_array=_h5_reader(member),
            )
            items.append((full, entry))
        elif isinstance(member, h5py.Group):
            items.extend(_collect_entries(member, full))
    return items


class HDF5Reader:
    """Lazy HDF5 decoder preserving hierarchical groups, attributes, and QA safety."""

    @property
    def data_format(self) -> DataFormat:
        return "hdf5"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header:
            return header.startswith(_HDF5_MAGIC)
        return asset.data_format == "hdf5" or asset.uri.lower().endswith((".h5", ".hdf5", ".he5"))

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            with h5py.File(path, mode="r") as h5f:
                root_attrs = to_attr_dict(h5f.attrs.items())
                entries = dict(_collect_entries(h5f))
                return decode_nd_container(asset, "hdf5", entries, root_attrs, variables)
        except OSError as exc:
            raise AssetDecodeError(f"Failed to decode HDF5 '{path.name}': {exc}") from exc
