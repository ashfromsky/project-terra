"""Shared lazy container adapter for HDF5, Zarr, and HDF4 array hierarchies."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    VariableSpec,
)
from geospatial_harmonization.readers._helpers import (
    canonical_crs_string,
    extract_cf_var_meta,
    grid_from_axes,
    select_variables,
)
from geospatial_harmonization.readers.registry import AssetDecodeError

_X_NAMES = frozenset({"lon", "longitude", "x", "xdim"})
_Y_NAMES = frozenset({"lat", "latitude", "y", "ydim"})


@dataclass(frozen=True, slots=True)
class NdVarEntry:
    """Lazy metadata handle and reader callback for one array/SDS variable."""

    name: str
    dimensions: tuple[str, ...]
    ndim: int
    size: int
    dtype_kind: str
    attributes: dict[str, object]
    read_array: Callable[[], object]


def resolve_container_axes(
    entries: dict[str, NdVarEntry], root_attrs: dict[str, object]
) -> tuple[str | None, list[float] | None, list[float] | None]:
    """Infer explicit CRS and 1D coordinate axes without fabricating missing CRS."""
    crs_str: str | None = None
    for key in ("crs_wkt", "spatial_ref", "crs", "EPSG"):
        if key in root_attrs and (crs_str := canonical_crs_string(root_attrs[key])):
            break

    xs: list[float] | None = None
    ys: list[float] | None = None
    has_lon_deg = False
    has_lat_deg = False

    for full_name, entry in entries.items():
        attrs = entry.attributes
        if crs_str is None:
            crs_str = canonical_crs_string(
                attrs.get("crs_wkt") or attrs.get("spatial_ref") or attrs.get("epsg_code")
            )
        if entry.ndim == 1 and 0 < entry.size <= 8192 and entry.dtype_kind in "biuf":
            leaf = full_name.rsplit("/", 1)[-1].lower()
            axis = str(attrs.get("axis", "")).upper()
            units = str(attrs.get("units", "")).lower()
            if axis == "X" or leaf in _X_NAMES:
                xs = [float(v) for v in np.asarray(entry.read_array()).tolist()]
                has_lon_deg = "degrees_east" in units
            elif axis == "Y" or leaf in _Y_NAMES:
                ys = [float(v) for v in np.asarray(entry.read_array()).tolist()]
                has_lat_deg = "degrees_north" in units

    if crs_str is None and has_lon_deg and has_lat_deg:
        crs_str = "EPSG:4326"
    return crs_str, xs, ys


def decode_nd_container(
    asset: AssetReference,
    fmt: DataFormat,
    entries: dict[str, NdVarEntry],
    root_attrs: dict[str, object],
    variables: tuple[str, ...] | None,
) -> DecodedDataset:
    """Decode selected NdVarEntry items into a canonical DecodedDataset."""
    if not entries:
        raise AssetDecodeError(f"{fmt.upper()} asset '{asset.asset_id}' contains no datasets")

    selected = select_variables(entries.keys(), variables)
    crs_str, xs, ys = resolve_container_axes(entries, root_attrs)
    grid, grid_warnings = grid_from_axes(crs_str, xs, ys)
    warnings = list(grid_warnings)

    var_specs: dict[str, VariableSpec] = {}
    arrays: dict[str, object] = {}
    coordinates: dict[str, tuple[float | int | str, ...]] = {}
    dimensions: dict[str, int] = {}

    for name in selected:
        entry = entries[name]
        arr = np.asarray(entry.read_array())
        is_num = arr.dtype.kind in "biufc"
        sem, scale, offset, nodata, var_warn = extract_cf_var_meta(name, entry.attributes, is_num)
        warnings.extend(var_warn)

        for dname, dsize in zip(entry.dimensions, arr.shape, strict=True):
            dimensions[dname] = int(dsize)
        arrays[name] = arr
        if sem == "coordinate" and arr.ndim == 1 and arr.size <= 8192:
            coordinates[name] = tuple(arr.tolist())
        var_specs[name] = VariableSpec(
            name=name,
            units=str(entry.attributes.get("units", "1")).strip() or "1",
            dtype=str(arr.dtype),
            dimensions=entry.dimensions,
            semantics=sem,
            nodata=nodata,
            scale_factor=scale,
            add_offset=offset,
            grid=grid if sem != "coordinate" else None,
            attributes=entry.attributes,
        )

    return DecodedDataset(
        asset=asset,
        data_format=fmt,
        variables=var_specs,
        dimensions=dimensions,
        coordinates=coordinates,
        arrays=arrays,
        attributes=root_attrs,
        crs=crs_str,
        grid=grid,
        warnings=tuple(warnings),
    )
