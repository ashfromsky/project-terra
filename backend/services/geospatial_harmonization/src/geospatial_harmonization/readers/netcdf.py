"""NetCDF-3 / NetCDF-4 / CF-convention AssetReader preserving dimension order."""

from pathlib import Path
from typing import Any

import netCDF4
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
    to_attr_dict,
)
from geospatial_harmonization.readers.registry import AssetDecodeError

_NETCDF_CLASSIC = (b"CDF\x01", b"CDF\x02", b"CDF\x05")
_X_NAMES = frozenset({"lon", "longitude", "x", "xdim"})
_Y_NAMES = frozenset({"lat", "latitude", "y", "ydim"})


def _collect_vars(group: Any, prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for name, var in group.variables.items():
        full = f"{prefix}/{name}" if prefix else str(name)
        items.append((full, var))
    for sub_name, sub_group in group.groups.items():
        sub_prefix = f"{prefix}/{sub_name}" if prefix else str(sub_name)
        items.extend(_collect_vars(sub_group, sub_prefix))
    return items


def _resolve_crs(
    var_map: dict[str, Any], global_attrs: dict[str, object]
) -> tuple[str | None, list[float] | None, list[float] | None]:
    crs_str: str | None = None
    for key in ("crs_wkt", "spatial_ref", "crs", "EPSG"):
        if key in global_attrs and (crs_str := canonical_crs_string(global_attrs[key])):
            break

    xs: list[float] | None = None
    ys: list[float] | None = None
    has_lon_deg = False
    has_lat_deg = False

    for full_name, nc_var in var_map.items():
        attrs = to_attr_dict((k, nc_var.getncattr(k)) for k in nc_var.ncattrs())
        if crs_str is None and any(
            k in attrs for k in ("grid_mapping_name", "crs_wkt", "spatial_ref")
        ):
            crs_str = canonical_crs_string(
                attrs.get("crs_wkt") or attrs.get("spatial_ref") or attrs.get("epsg_code")
            )
        gm_name = str(attrs.get("grid_mapping", ""))
        prefix = full_name.rsplit("/", 1)[0] if "/" in full_name else ""
        gm_key = gm_name if gm_name in var_map else (f"{prefix}/{gm_name}" if prefix else gm_name)
        if crs_str is None and gm_key in var_map:
            gm = var_map[gm_key]
            gm_attrs = to_attr_dict((k, gm.getncattr(k)) for k in gm.ncattrs())
            crs_str = canonical_crs_string(
                gm_attrs.get("crs_wkt") or gm_attrs.get("spatial_ref") or gm_attrs.get("epsg_code")
            )

        if nc_var.ndim == 1 and nc_var.size > 0 and nc_var.dtype.kind in "biuf":
            leaf = full_name.rsplit("/", 1)[-1].lower()
            axis = str(attrs.get("axis", "")).upper()
            units = str(attrs.get("units", "")).lower()
            if axis == "X" or leaf in _X_NAMES:
                xs = [float(v) for v in np.asarray(nc_var[:]).tolist()]
                has_lon_deg = "degrees_east" in units
            elif axis == "Y" or leaf in _Y_NAMES:
                ys = [float(v) for v in np.asarray(nc_var[:]).tolist()]
                has_lat_deg = "degrees_north" in units

    if crs_str is None and has_lon_deg and has_lat_deg:
        crs_str = "EPSG:4326"
    return crs_str, xs, ys


class NetCDFReader:
    """Lazy CF-aware decoder for NetCDF-3 and grouped NetCDF-4 datasets."""

    @property
    def data_format(self) -> DataFormat:
        return "netcdf"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header.startswith(_NETCDF_CLASSIC):
            return True
        return asset.data_format == "netcdf" or asset.uri.lower().endswith(
            (".nc", ".nc4", ".cdf", ".netcdf")
        )

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            with netCDF4.Dataset(path, mode="r") as ds:
                global_attrs = to_attr_dict((k, ds.getncattr(k)) for k in ds.ncattrs())
                var_map = dict(_collect_vars(ds))
                if not var_map:
                    raise AssetDecodeError(f"NetCDF '{path.name}' contains no variables")

                selected = select_variables(var_map.keys(), variables)
                crs_str, xs, ys = _resolve_crs(var_map, global_attrs)
                grid, grid_warnings = grid_from_axes(crs_str, xs, ys)
                warnings = list(grid_warnings)

                var_specs: dict[str, VariableSpec] = {}
                arrays: dict[str, object] = {}
                coordinates: dict[str, tuple[float | int | str, ...]] = {}
                dimensions: dict[str, int] = {}

                for name in selected:
                    nc_var = var_map[name]
                    nc_var.set_auto_maskandscale(False)
                    attrs = to_attr_dict((k, nc_var.getncattr(k)) for k in nc_var.ncattrs())
                    arr = np.asarray(nc_var[:])
                    is_num = arr.dtype.kind in "biufc"
                    sem, scale, offset, nodata, var_warn = extract_cf_var_meta(name, attrs, is_num)
                    warnings.extend(var_warn)

                    dim_names = tuple(str(d) for d in nc_var.dimensions)
                    for dname, dsize in zip(dim_names, arr.shape, strict=True):
                        dimensions[dname] = int(dsize)

                    arrays[name] = arr
                    if sem == "coordinate" and arr.ndim == 1 and arr.size <= 8192:
                        coordinates[name] = tuple(arr.tolist())
                    var_specs[name] = VariableSpec(
                        name=name,
                        units=str(attrs.get("units", "1")).strip() or "1",
                        dtype=str(arr.dtype),
                        dimensions=dim_names,
                        semantics=sem,
                        nodata=nodata,
                        scale_factor=scale,
                        add_offset=offset,
                        grid=grid if sem != "coordinate" else None,
                        attributes=attrs,
                    )

                return DecodedDataset(
                    asset=asset,
                    data_format="netcdf",
                    variables=var_specs,
                    dimensions=dimensions,
                    coordinates=coordinates,
                    arrays=arrays,
                    attributes=global_attrs,
                    crs=crs_str,
                    grid=grid,
                    warnings=tuple(warnings),
                )
        except (OSError, RuntimeError) as exc:
            raise AssetDecodeError(f"Failed to decode NetCDF '{path.name}': {exc}") from exc
