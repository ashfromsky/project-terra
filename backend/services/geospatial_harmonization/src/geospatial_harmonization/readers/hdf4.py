"""HDF4 / HDF-EOS2 AssetReader using pyhdf without product-specific conditionals."""

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from pyhdf.SD import SD, SDC, HDF4Error

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
)
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.readers._helpers import (
    build_grid_from_affine,
    canonical_crs_string,
    to_attr_dict,
)
from geospatial_harmonization.readers._nd_container import NdVarEntry, decode_nd_container
from geospatial_harmonization.readers.registry import AssetDecodeError

_HDF4_MAGIC = b"\x0e\x03\x13\x01"
_MODIS_SINU_PROJ = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
_SDC_KINDS: dict[int, str] = {
    SDC.FLOAT32: "f",
    SDC.FLOAT64: "f",
    SDC.INT8: "i",
    SDC.INT16: "i",
    SDC.INT32: "i",
    SDC.UINT8: "u",
    SDC.UINT16: "u",
    SDC.UINT32: "u",
    SDC.CHAR: "S",
    SDC.UCHAR: "S",
}


def _sds_reader(sd: SD, name: str) -> Callable[[], object]:
    def _read() -> object:
        sds = sd.select(name)
        try:
            return sds.get()
        finally:
            sds.endaccess()

    return _read


def _parse_hdf_eos_grid(root_attrs: dict[str, object]) -> tuple[str | None, GridSpec | None]:
    raw_meta = str(root_attrs.get("StructMetadata.0", "") or root_attrs.get("StructMetadata_0", ""))
    if not raw_meta:
        return None, None

    proj_m = re.search(r"Projection\s*=\s*(\w+)", raw_meta)
    x_m = re.search(r"XDim\s*=\s*(\d+)", raw_meta)
    y_m = re.search(r"YDim\s*=\s*(\d+)", raw_meta)
    ul_m = re.search(r"UpperLeftPointMtrs\s*=\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)", raw_meta)
    lr_m = re.search(r"LowerRightMtrs\s*=\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)", raw_meta)
    if not (proj_m and x_m and y_m and ul_m and lr_m):
        return None, None

    proj_name = proj_m.group(1)
    crs_str: str | None = None
    if proj_name == "GCTP_SNSOID":
        crs_str = canonical_crs_string(_MODIS_SINU_PROJ)
    elif proj_name == "GCTP_GEO":
        crs_str = "EPSG:4326"
    if crs_str is None:
        return None, None

    width, height = int(x_m.group(1)), int(y_m.group(1))
    ul_x, ul_y = float(ul_m.group(1)), float(ul_m.group(2))
    lr_x, lr_y = float(lr_m.group(1)), float(lr_m.group(2))
    if width <= 0 or height <= 0 or lr_x <= ul_x or ul_y <= lr_y:
        return crs_str, None

    px_w, px_h = (lr_x - ul_x) / width, (ul_y - lr_y) / height
    grid, _ = build_grid_from_affine(crs_str, (px_w, 0.0, ul_x, 0.0, -px_h, ul_y), width, height)
    return crs_str, grid


class HDF4Reader:
    """Lazy HDF4 / HDF-EOS2 Scientific Data Set decoder using pyhdf."""

    @property
    def data_format(self) -> DataFormat:
        return "hdf4"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header:
            return header.startswith(_HDF4_MAGIC)
        return asset.data_format == "hdf4" or asset.uri.lower().endswith((".hdf", ".hdf4", ".h4"))

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            sd = SD(str(path), SDC.READ)
        except HDF4Error as exc:
            raise AssetDecodeError(f"Failed to decode HDF4 '{path.name}': {exc}") from exc

        try:
            root_attrs = to_attr_dict(sd.attributes().items())
            entries: dict[str, NdVarEntry] = {}
            for name, (dim_names, shape, type_code, _) in sd.datasets().items():
                sds = sd.select(name)
                try:
                    attrs = to_attr_dict(sds.attributes().items())
                finally:
                    sds.endaccess()
                dims = tuple(str(d) for d in dim_names)
                size = 1
                for extent in shape:
                    size *= int(extent)
                entries[str(name)] = NdVarEntry(
                    name=str(name),
                    dimensions=dims,
                    ndim=len(shape),
                    size=size,
                    dtype_kind=_SDC_KINDS.get(int(type_code), "f"),
                    attributes=attrs,
                    read_array=_sds_reader(sd, str(name)),
                )

            decoded = decode_nd_container(asset, "hdf4", entries, root_attrs, variables)
        except HDF4Error as exc:
            raise AssetDecodeError(f"Failed to read HDF4 dataset '{path.name}': {exc}") from exc
        finally:
            sd.end()

        if decoded.grid is None:
            eos_crs, eos_grid = _parse_hdf_eos_grid(root_attrs)
            if eos_grid is not None:
                filtered_warn = tuple(
                    w for w in decoded.warnings if "skipped" not in w.lower() and "CRS" not in w
                )
                new_vars = {
                    k: replace(v, grid=eos_grid) if v.semantics != "coordinate" else v
                    for k, v in decoded.variables.items()
                }
                return replace(
                    decoded, crs=eos_crs, grid=eos_grid, variables=new_vars, warnings=filtered_warn
                )
        return decoded
