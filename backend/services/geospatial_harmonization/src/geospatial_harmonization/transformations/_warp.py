"""Universal spatial reprojection, axis orientation, and COG GeoTIFF export."""

import math
import os
import uuid
import warnings as py_warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from pyproj import Geod, Transformer
from rasterio.errors import NotGeoreferencedWarning, WindowError
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    StorageImmutabilityError,
)
from geospatial_harmonization.domain.models.dataset import VariableSpec
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import ResamplingMethod
from geospatial_harmonization.domain.models.storage import (
    CompressionPolicy,
    CompressionResult,
    PrecisionPolicy,
)
from geospatial_harmonization.storage.compression import (
    geotiff_creation_options,
    policy_from_settings,
    validate_precision_transition,
)

_RESAMPLING_MAP: dict[ResamplingMethod, Resampling] = {
    "nearest": Resampling.nearest,
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
    "sum": Resampling.sum,
    "mode": Resampling.mode,
}
_X_DIMS = frozenset({"x", "xdim", "lon", "longitude"})
_Y_DIMS = frozenset({"y", "ydim", "lat", "latitude"})
_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True, slots=True)
class WarpedVariable:
    """In-memory warped raster result paired with target nodata and pixel counts."""

    data: NDArray[np.generic]
    nodata: float | int | None
    valid_pixels: int
    total_pixels: int


def to_rasterio_affine(grid: GridSpec) -> Affine:
    res = grid.resolved()
    t = res.transform
    assert t is not None
    if res.pixel_convention == "center":
        return Affine(
            t.a,
            t.b,
            t.c - 0.5 * t.a - 0.5 * t.b,
            t.d,
            t.e,
            t.f - 0.5 * t.d - 0.5 * t.e,
        )
    return Affine(t.a, t.b, t.c, t.d, t.e, t.f)


def _pixel_ground_meters(grid: GridSpec) -> tuple[float, float]:
    res = grid.resolved()
    b = res.bounds
    cx, cy = 0.5 * (b.min_x + b.max_x), 0.5 * (b.min_y + b.max_y)
    to_geo = Transformer.from_crs(res.crs, "EPSG:4326", always_xy=True)
    lon0, lat0 = to_geo.transform(cx, cy)
    lonx, latx = to_geo.transform(cx + res.resolution_x, cy)
    lony, laty = to_geo.transform(cx, cy + res.resolution_y)
    lat0_c = max(-89.9, min(89.9, lat0))
    _, _, dx = _GEOD.inv(lon0, lat0_c, lonx, max(-89.9, min(89.9, latx)))
    _, _, dy = _GEOD.inv(lon0, lat0_c, lony, max(-89.9, min(89.9, laty)))
    return abs(float(dx)), abs(float(dy))


def check_upsampling_warning(src_grid: GridSpec, dst_grid: GridSpec) -> str | None:
    """Emit resolution-fidelity warning if target spacing is finer than native grid."""
    if src_grid.crs == dst_grid.crs:
        finer = (
            dst_grid.resolution_x < src_grid.resolution_x * 0.99
            or dst_grid.resolution_y < src_grid.resolution_y * 0.99
        )
    else:
        sx, sy = _pixel_ground_meters(src_grid)
        dx, dy = _pixel_ground_meters(dst_grid)
        finer = dx < sx * 0.99 or dy < sy * 0.99
    if finer:
        return "Target grid is finer than source grid (upsampling); no native detail is added."
    return None


def _find_coord(
    dim_name: str, coordinates: dict[str, tuple[float | int | str, ...]]
) -> tuple[float | int | str, ...] | None:
    if dim_name in coordinates:
        return coordinates[dim_name]
    return next((v for k, v in coordinates.items() if k.rsplit("/", 1)[-1] == dim_name), None)


def orient_to_north_up(
    arr: NDArray[np.generic],
    dims: tuple[str, ...],
    coordinates: dict[str, tuple[float | int | str, ...]],
) -> tuple[NDArray[np.generic], tuple[str, ...]]:
    """Reorder axes to (..., y, x) and orient North-to-South, West-to-East."""
    if arr.ndim < 2 or len(dims) != arr.ndim:
        raise IncompatibleDatasetError("Grid variable must be at least 2D with matching dimensions")
    lower = [d.lower() for d in dims]
    y_idx = next((i for i, d in enumerate(lower) if d in _Y_DIMS), arr.ndim - 2)
    x_idx = next((i for i, d in enumerate(lower) if d in _X_DIMS), arr.ndim - 1)
    if y_idx == x_idx:
        raise IncompatibleDatasetError(f"Ambiguous spatial dimensions: {dims}")

    reordered = np.moveaxis(arr, (y_idx, x_idx), (-2, -1))
    leading = tuple(d for i, d in enumerate(dims) if i not in (y_idx, x_idx))
    y_coords = _find_coord(dims[y_idx], coordinates)
    if y_coords and len(y_coords) >= 2 and float(y_coords[0]) < float(y_coords[-1]):
        reordered = np.flip(reordered, axis=-2)
    x_coords = _find_coord(dims[x_idx], coordinates)
    if x_coords and len(x_coords) >= 2 and float(x_coords[0]) > float(x_coords[-1]):
        reordered = np.flip(reordered, axis=-1)
    return reordered, (*leading, "y", "x")


def warp_variable(
    raw_arr: NDArray[np.generic],
    spec: VariableSpec,
    src_grid: GridSpec,
    dst_grid: GridSpec,
    method: ResamplingMethod,
    coordinates: dict[str, tuple[float | int | str, ...]],
    *,
    precision: PrecisionPolicy | None = None,
    target_dtype: str | None = None,
) -> tuple[WarpedVariable, tuple[str, ...]]:
    """Scale continuous data safely, orient spatial axes, and warp onto target grid."""
    src_res, dst_res = src_grid.resolved(), dst_grid.resolved()
    oriented, out_dims = orient_to_north_up(raw_arr, spec.dimensions, coordinates)
    if oriented.shape[-2:] != (src_res.height, src_res.width):
        raise IncompatibleDatasetError(
            f"Variable '{spec.name}' spatial shape {oriented.shape[-2:]} != "
            f"source grid {(src_res.height, src_res.width)}"
        )

    prec = precision or PrecisionPolicy()
    raw_dt = np.dtype(raw_arr.dtype)
    spec_dt = np.dtype(spec.dtype)
    discrete = spec.semantics in ("qa_flag", "categorical")
    if discrete:
        work: NDArray[np.generic] = oriented
        src_nd: float | int | None = spec.nodata
        dst_nd: float | int | None = spec.nodata if isinstance(spec.nodata, (int, float)) else None
        fill_val: float | int = dst_nd if dst_nd is not None else 0
    else:
        scaled: NDArray[np.float64] = oriented.astype(np.float64, copy=True)
        if spec.nodata is not None:
            nd = float(spec.nodata)
            scaled[np.isnan(scaled) if math.isnan(nd) else (scaled == nd)] = np.nan
        if spec.scale_factor is not None:
            scaled *= spec.scale_factor
        if spec.add_offset is not None:
            scaled += spec.add_offset
        work = scaled
        src_nd = dst_nd = fill_val = np.nan

    assert dst_res.height is not None and dst_res.width is not None
    lead_shape = work.shape[:-2]
    out = np.full((*lead_shape, dst_res.height, dst_res.width), fill_val, dtype=work.dtype)
    src_t, dst_t = to_rasterio_affine(src_res), to_rasterio_affine(dst_res)

    for idx in np.ndindex(lead_shape) if lead_shape else ((),):
        src_slice = np.ascontiguousarray(work[idx] if idx else work)
        dst_slice = np.ascontiguousarray(out[idx] if idx else out)
        with py_warnings.catch_warnings():
            py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
            reproject(
                source=src_slice,
                destination=dst_slice,
                src_transform=src_t,
                src_crs=src_res.crs,
                dst_transform=dst_t,
                dst_crs=dst_res.crs,
                src_nodata=src_nd,
                dst_nodata=dst_nd,
                resampling=_RESAMPLING_MAP[method],
            )
        if idx:
            out[idx] = dst_slice
        else:
            out = dst_slice

    if discrete:
        if target_dtype is not None:
            validate_precision_transition(raw_dt, target_dtype, prec)
            out = out.astype(np.dtype(target_dtype), copy=False)
        valid = int(out.size) if dst_nd is None else int(np.count_nonzero(out != dst_nd))
        return WarpedVariable(out, dst_nd, valid, int(out.size)), out_dims

    if target_dtype is not None:
        ref_dt = np.dtype(np.float64) if (raw_dt == np.float64 or spec_dt == np.float64) else raw_dt
        validate_precision_transition(ref_dt, target_dtype, prec)
        final_dt = np.dtype(target_dtype)
    else:
        needs_float64 = prec.preserve_float64 and (
            raw_dt == np.float64
            or spec_dt == np.float64
            or (spec_dt.kind in ("i", "u") and spec_dt.itemsize >= 4)
            or (raw_dt.kind in ("i", "u") and raw_dt.itemsize >= 4)
        )
        final_dt = np.dtype(np.float64 if needs_float64 else np.float32)

    out = out.astype(final_dt, copy=False)
    valid = int(np.count_nonzero(np.isfinite(out)))
    return WarpedVariable(out, np.nan, valid, int(out.size)), out_dims


def write_variable_geotiff(
    out_path: Path,
    warped: WarpedVariable,
    grid: GridSpec,
    var_name: str,
    tags: dict[str, str],
    *,
    compression: CompressionPolicy | None = None,
    units: str | None = None,
) -> None:
    """Persist warped 2D/3D array to a lossless GeoTIFF/COG preserving exact dtype."""
    res = grid.resolved()
    assert res.width is not None and res.height is not None
    arr = warped.data
    bands = arr.reshape((-1, res.height, res.width)) if arr.ndim > 2 else arr[np.newaxis, :, :]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nodata = warped.nodata if isinstance(warped.nodata, (int, float)) else None
    policy = compression or policy_from_settings()
    creation_opts = geotiff_creation_options(
        bands.dtype, policy, estimated_raw_bytes=int(bands.nbytes)
    )
    tmp_path = out_path.with_name(f".ghs-tmp-{uuid.uuid4().hex[:10]}.tif")
    try:
        with rasterio.open(
            tmp_path,
            "w",
            height=res.height,
            width=res.width,
            count=int(bands.shape[0]),
            dtype=str(bands.dtype),
            crs=res.crs,
            transform=to_rasterio_affine(res),
            nodata=nodata if nodata is not None else (np.nan if bands.dtype.kind == "f" else None),
            **creation_opts,
        ) as dst:
            for bidx in range(bands.shape[0]):
                dst.write(bands[bidx], bidx + 1)
                dst.set_band_description(
                    bidx + 1, var_name if bands.shape[0] == 1 else f"{var_name}_{bidx}"
                )
            if units:
                dst.units = (units,) * int(bands.shape[0])
            dst.update_tags(**tags)
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def clip_raster_to_aoi(
    src_path: Path,
    dst_path: Path,
    *,
    aoi_bounds: SpatialBounds,
    aoi_crs: str | None = None,
    compression: CompressionPolicy | None = None,
) -> CompressionResult:
    """Clip a raster losslessly using windowed reading without mutating the source file."""
    if src_path.resolve() == dst_path.resolve():
        raise StorageImmutabilityError(
            f"Cannot overwrite source raster '{src_path}' during AOI clipping"
        )
    policy = compression or policy_from_settings()
    orig_bytes = src_path.stat().st_size

    with py_warnings.catch_warnings():
        py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
        src = rasterio.open(src_path)

    with src:
        target_bounds = aoi_bounds.as_tuple()
        if aoi_crs is not None:
            if src.crs is None:
                raise IncompatibleDatasetError(
                    f"Source raster '{src_path.name}' lacks CRS required to transform AOI"
                )
            if aoi_crs != src.crs.to_string():
                target_bounds = transform_bounds(aoi_crs, src.crs, *target_bounds, densify_pts=21)

        raw_win = from_bounds(*target_bounds, transform=src.transform)
        full_win = Window(0, 0, int(src.width), int(src.height))
        try:
            bounded = raw_win.round_offsets().round_lengths().intersection(full_win)
        except WindowError as exc:
            raise IncompatibleDatasetError(
                f"AOI bounds {target_bounds} do not intersect source raster '{src_path.name}'"
            ) from exc
        if bounded.width <= 0 or bounded.height <= 0:
            raise IncompatibleDatasetError(
                f"AOI bounds {target_bounds} produced empty intersection for '{src_path.name}'"
            )

        clip_transform = src.window_transform(bounded)
        primary_dt = np.dtype(src.dtypes[0])
        creation_opts = geotiff_creation_options(
            primary_dt,
            policy,
            estimated_raw_bytes=int(bounded.width)
            * int(bounded.height)
            * int(src.count)
            * primary_dt.itemsize,
        )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dst_path.with_name(f".ghs-tmp-{uuid.uuid4().hex[:10]}.tif")
        preserved: set[str] = set()
        try:
            with rasterio.open(
                tmp_path,
                "w",
                height=int(bounded.height),
                width=int(bounded.width),
                count=int(src.count),
                dtype=str(primary_dt),
                crs=src.crs,
                transform=clip_transform,
                nodata=src.nodatavals[0] if src.nodatavals else src.nodata,
                **creation_opts,
            ) as dst:
                for bidx in src.indexes:
                    dst.write(src.read(bidx, window=bounded), bidx)
                    if src.descriptions[bidx - 1]:
                        dst.set_band_description(bidx, src.descriptions[bidx - 1])
                    b_tags = src.tags(bidx)
                    if b_tags:
                        dst.update_tags(bidx, **b_tags)
                        preserved.update(str(k) for k in b_tags)
                dst.scales = src.scales
                dst.offsets = src.offsets
                dst.units = src.units
                g_tags = src.tags()
                if g_tags:
                    dst.update_tags(**g_tags)
                    preserved.update(str(k) for k in g_tags)
            comp_bytes = tmp_path.stat().st_size
            os.replace(tmp_path, dst_path)
            return CompressionResult(
                output_path=str(dst_path),
                data_format="geotiff",
                codec=str(creation_opts.get("compress", "none")),
                original_bytes=orig_bytes,
                compressed_bytes=comp_bytes,
                saved_bytes=max(0, orig_bytes - comp_bytes),
                metadata_preserved=tuple(sorted(preserved)),
            )
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
