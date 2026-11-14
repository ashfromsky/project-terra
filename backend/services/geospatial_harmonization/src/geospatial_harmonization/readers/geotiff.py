"""GeoTIFF / COG AssetReader using rasterio without inventing missing CRS metadata."""

import math
import warnings as py_warnings
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.errors import NotGeoreferencedWarning, RasterioError, WindowError
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import SpatialBounds
from geospatial_harmonization.readers._helpers import (
    as_float,
    build_grid_from_affine,
    canonical_crs_string,
    infer_variable_semantics,
    select_variables,
)
from geospatial_harmonization.readers.registry import AssetDecodeError

_TIFF_PREFIXES = (b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b")


def _extract_geotiff_decoded(
    src: Any,
    asset: AssetReference,
    *,
    variables: tuple[str, ...] | None,
    window: Window | None,
    extra_note: str | None = None,
    fill_disjoint_nodata: bool = False,
) -> DecodedDataset:
    band_names: dict[str, int] = {}
    for bidx in src.indexes:
        desc = (src.descriptions[bidx - 1] or "").strip()
        name = desc if desc and desc not in band_names else f"band_{bidx}"
        band_names[name] = int(bidx)

    selected = select_variables(band_names.keys(), variables)
    crs_str = canonical_crs_string(src.crs)
    t = src.transform if window is None else src.window_transform(window)
    width = int(src.width) if window is None else int(window.width)
    height = int(src.height) if window is None else int(window.height)
    grid, warnings = build_grid_from_affine(crs_str, (t.a, t.b, t.c, t.d, t.e, t.f), width, height)

    var_specs: dict[str, VariableSpec] = {}
    arrays: dict[str, object] = {}
    extra_warnings = list(warnings)
    if extra_note:
        extra_warnings.append(extra_note)
    for name in selected:
        bidx = band_names[name]
        tags = {str(k): v for k, v in src.tags(bidx).items()}
        semantics = infer_variable_semantics(name, tags)
        scale = as_float(src.scales[bidx - 1])
        offset = as_float(src.offsets[bidx - 1])
        scale = None if scale == 1.0 else scale
        offset = None if offset == 0.0 else offset
        if semantics in ("qa_flag", "categorical") and (scale is not None or offset is not None):
            extra_warnings.append(f"Dropped scaling on '{name}' ({semantics})")
            scale, offset = None, None
        nodata = src.nodatavals[bidx - 1]
        unit = (src.units[bidx - 1] or "").strip() or "1"
        arr = np.asarray(src.read(bidx) if window is None else src.read(bidx, window=window))
        if fill_disjoint_nodata:
            arr = arr.copy()
            if isinstance(nodata, (int, float)):
                arr.fill(nodata)
            elif arr.dtype.kind == "f":
                arr.fill(np.nan)
        arrays[name] = arr
        var_specs[name] = VariableSpec(
            name=name,
            units=unit,
            dtype=str(arr.dtype),
            dimensions=("y", "x"),
            semantics=semantics,
            nodata=nodata if isinstance(nodata, (int, float)) else None,
            scale_factor=scale,
            add_offset=offset,
            grid=grid,
            attributes=tags,
        )

    global_tags = {str(k): v for k, v in src.tags().items()}
    return DecodedDataset(
        asset=asset,
        data_format="geotiff",
        variables=var_specs,
        dimensions={"y": height, "x": width},
        arrays=arrays,
        attributes=global_tags,
        crs=crs_str,
        grid=grid,
        nodata=src.nodata if isinstance(src.nodata, (int, float)) else None,
        warnings=tuple(extra_warnings),
    )


class GeoTIFFReader:
    """Lazy raster decoder for GeoTIFF and Cloud-Optimized GeoTIFF files."""

    @property
    def data_format(self) -> DataFormat:
        return "geotiff"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header:
            return header.startswith(_TIFF_PREFIXES)
        return asset.data_format == "geotiff" or asset.uri.lower().endswith(
            (".tif", ".tiff", ".geotiff")
        )

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            with py_warnings.catch_warnings():
                py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
                src = rasterio.open(path)
            with src:
                return _extract_geotiff_decoded(src, asset, variables=variables, window=None)
        except RasterioError as exc:
            raise AssetDecodeError(f"Failed to decode GeoTIFF '{path.name}': {exc}") from exc

    def read_windowed(
        self,
        asset: AssetReference,
        path: Path,
        *,
        aoi_bounds: SpatialBounds,
        aoi_crs: str | None = None,
        variables: tuple[str, ...] | None = None,
        pad_pixels: int = 2,
        allow_disjoint_fallback: bool = True,
    ) -> DecodedDataset:
        """Read only the buffered raster window overlapping an AOI without modifying source."""
        try:
            with py_warnings.catch_warnings():
                py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
                src = rasterio.open(path)
            with src:
                bounds_tuple = aoi_bounds.as_tuple()
                if aoi_crs is not None:
                    if src.crs is None:
                        return _extract_geotiff_decoded(
                            src,
                            asset,
                            variables=variables,
                            window=None,
                            extra_note=(
                                "Source GeoTIFF lacks CRS; fell back to full raster decode."
                            ),
                        )
                    if CRS.from_user_input(aoi_crs) != CRS.from_user_input(src.crs):
                        bounds_tuple = transform_bounds(
                            aoi_crs, src.crs, *bounds_tuple, densify_pts=21
                        )

                raw_win = from_bounds(*bounds_tuple, transform=src.transform)
                c0 = math.floor(min(raw_win.col_off, raw_win.col_off + raw_win.width)) - pad_pixels
                c1 = math.ceil(max(raw_win.col_off, raw_win.col_off + raw_win.width)) + pad_pixels
                r0 = math.floor(min(raw_win.row_off, raw_win.row_off + raw_win.height)) - pad_pixels
                r1 = math.ceil(max(raw_win.row_off, raw_win.row_off + raw_win.height)) + pad_pixels
                padded = Window(c0, r0, max(0, c1 - c0), max(0, r1 - r0))
                full = Window(0, 0, int(src.width), int(src.height))
                try:
                    bounded = padded.intersection(full)
                except WindowError:
                    bounded = Window(0, 0, 0, 0)

                if bounded.width <= 0 or bounded.height <= 0:
                    if not allow_disjoint_fallback:
                        raise AssetDecodeError(f"AOI bounds do not intersect GeoTIFF '{path.name}'")
                    return _extract_geotiff_decoded(
                        src,
                        asset,
                        variables=variables,
                        window=Window(0, 0, 1, 1),
                        extra_note="AOI does not overlap raster; decoded minimal corner cell.",
                        fill_disjoint_nodata=True,
                    )

                return _extract_geotiff_decoded(src, asset, variables=variables, window=bounded)
        except RasterioError as exc:
            raise AssetDecodeError(f"Failed to decode GeoTIFF '{path.name}': {exc}") from exc
