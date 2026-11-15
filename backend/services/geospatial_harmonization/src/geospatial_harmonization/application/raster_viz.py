"""Raster tile rendering, bounding-box PNG export, and point pixel inspection for GHS."""

import asyncio
import math
import struct
import tempfile
import zlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer
from rasterio.errors import WindowError
from rasterio.warp import transform_bounds

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    SpatialDataset,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.ports import StoragePort
from geospatial_harmonization.readers import ReaderRegistry
from geospatial_harmonization.transformations._warp import (
    orient_to_north_up,
    to_rasterio_affine,
    warp_variable,
)

_ORIGIN_SHIFT = 20037508.342789244
_SUPPORTED_RASTER_FORMATS: frozenset[DataFormat] = frozenset({"geotiff", "hdf4", "hdf5", "netcdf"})
_QA_TOKENS = ("qa", "qc", "qual", "flag", "reliability", "bitmask", "lat", "lon")


class UnsupportedRasterFormatError(IncompatibleDatasetError):
    """Raised when a dataset lacks a renderable raster asset (e.g. Zarr or tabular JSON/CSV)."""


class RasterAssetUnavailableError(IncompatibleDatasetError):
    """Raised when no materialized asset file can be opened from storage."""


class RasterVariableNotFoundError(IncompatibleDatasetError):
    """Raised when a requested raster variable is absent from the decoded asset."""


_ColorStop = tuple[float, tuple[int, int, int]]

_COLOR_RAMPS: dict[str, tuple[float, float, tuple[_ColorStop, ...]]] = {
    "ndvi": (
        0.0,
        1.0,
        (
            (0.0, (223, 184, 146)),
            (0.25, (231, 223, 186)),
            (0.55, (162, 212, 180)),
            (0.85, (21, 155, 145)),
            (1.0, (15, 92, 58)),
        ),
    ),
    "evi": (
        0.0,
        0.8,
        (
            (0.0, (229, 203, 176)),
            (0.28, (220, 228, 194)),
            (0.56, (142, 199, 190)),
            (0.88, (14, 124, 116)),
            (1.0, (13, 79, 54)),
        ),
    ),
    "lst_celsius": (
        -10.0,
        45.0,
        (
            (0.0, (49, 147, 206)),
            (0.40, (164, 207, 202)),
            (0.65, (234, 214, 188)),
            (1.0, (199, 127, 109)),
        ),
    ),
    "precip": (
        0.0,
        25.0,
        (
            (0.0, (247, 251, 255)),
            (0.15, (198, 219, 239)),
            (0.40, (107, 174, 214)),
            (0.70, (33, 113, 181)),
            (1.0, (8, 48, 107)),
        ),
    ),
    "soil_moisture": (
        0.02,
        0.55,
        (
            (0.0, (222, 180, 159)),
            (0.30, (232, 233, 219)),
            (0.60, (145, 198, 188)),
            (1.0, (49, 147, 206)),
        ),
    ),
    "viridis": (
        0.0,
        1.0,
        (
            (0.0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.50, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1.0, (253, 231, 37)),
        ),
    ),
}


def encode_rgba_png(rgba: NDArray[np.uint8]) -> bytes:
    """Encode an (H, W, 4) uint8 RGBA array cleanly as a PNG binary payload."""
    arr = np.ascontiguousarray(rgba, dtype=np.uint8)
    height, width, channels = arr.shape
    if channels != 4:
        raise ValueError(f"Expected 4-channel RGBA array, got shape {arr.shape}")

    raw_rows = b"".join(b"\x00" + arr[row].tobytes() for row in range(height))
    compressed = zlib.compress(raw_rows, level=6)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", compressed),
            _chunk(b"IEND", b""),
        )
    )


def _transparent_png(width: int, height: int) -> bytes:
    return encode_rgba_png(np.zeros((height, width, 4), dtype=np.uint8))


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Compute Web Mercator (EPSG:3857) bounds for an XYZ tile."""
    n = float(2**z)
    tile_span = (2.0 * _ORIGIN_SHIFT) / n
    min_x = -_ORIGIN_SHIFT + x * tile_span
    max_x = min_x + tile_span
    max_y = _ORIGIN_SHIFT - y * tile_span
    min_y = max_y - tile_span
    return (min_x, min_y, max_x, max_y)


def _dataset_wgs84_bounds(dataset: SpatialDataset) -> tuple[float, float, float, float] | None:
    bounds = dataset.spatial_metadata.bounds
    crs = dataset.spatial_metadata.crs
    if bounds is not None:
        if crs is None or "4326" in crs:
            return bounds.as_tuple()
        w, s, e, n = transform_bounds(crs, "EPSG:4326", *bounds.as_tuple(), densify_pts=21)
        return (float(w), float(s), float(e), float(n))
    grid = dataset.spatial_metadata.grid
    if grid is not None:
        gb = grid.bounds.as_tuple()
        if "4326" in grid.crs:
            return gb
        w, s, e, n = transform_bounds(grid.crs, "EPSG:4326", *gb, densify_pts=21)
        return (float(w), float(s), float(e), float(n))
    return None


def _bounds_intersect(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _extract_timestamps_list(dataset: SpatialDataset, variable: str | None) -> list[str]:
    ts_ext = dataset.extensions.get("time_series")
    if not isinstance(ts_ext, Mapping):
        return []
    if variable and isinstance(ts_ext.get(variable), Mapping):
        raw_ts = ts_ext[variable].get("timestamps")
        if isinstance(raw_ts, list):
            return [str(t) for t in raw_ts]
    for entry in ts_ext.values():
        if isinstance(entry, Mapping):
            raw_ts = entry.get("timestamps")
            if isinstance(raw_ts, list) and raw_ts:
                return [str(t) for t in raw_ts]
    return []


def _select_step_index(timestamps: list[str], timestamp: str | None) -> int:
    if not timestamps or not timestamp:
        return 0
    target = timestamp.strip()
    target_date = target[:10]
    for idx, ts in enumerate(timestamps):
        if ts == target or ts[:10] == target_date:
            return idx
    try:
        target_dt = datetime.fromisoformat(target.replace("Z", "+00:00"))
    except ValueError:
        return 0
    best_idx = 0
    best_diff: float | None = None
    for idx, ts in enumerate(timestamps):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        diff = abs((dt - target_dt).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = idx
    return best_idx


def _select_raster_asset(
    dataset: SpatialDataset,
    *,
    timestamp: str | None = None,
    variable: str | None = None,
) -> tuple[AssetReference, int]:
    if not dataset.assets:
        raise RasterAssetUnavailableError(f"Dataset '{dataset.dataset_id}' has no stored assets.")
    raster_assets = [a for a in dataset.assets if a.data_format in _SUPPORTED_RASTER_FORMATS]
    if not raster_assets:
        formats = ", ".join(sorted({a.data_format for a in dataset.assets}))
        raise UnsupportedRasterFormatError(
            f"Dataset '{dataset.dataset_id}' assets ({formats}) "
            "are not directly renderable raster formats."
        )
    timestamps = _extract_timestamps_list(dataset, variable)
    step_idx = _select_step_index(timestamps, timestamp)
    if len(raster_assets) == 1:
        return raster_assets[0], step_idx
    if timestamp:
        compact_date = timestamp[:10].replace("-", "")
        for asset in raster_assets:
            haystack = f"{asset.asset_id} {asset.storage_key or ''} {asset.uri}"
            if compact_date in haystack or timestamp[:10] in haystack:
                return asset, 0
    asset_idx = min(step_idx, len(raster_assets) - 1)
    return raster_assets[asset_idx], 0


def _local_path_from_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        candidate = Path(unquote(parsed.path))
        return candidate if candidate.is_file() else None
    if not parsed.scheme:
        candidate = Path(uri)
        return candidate if candidate.is_file() else None
    return None


async def _materialize_asset(
    asset: AssetReference,
    storage: StoragePort | None,
    tmp_dir: Path,
) -> Path:
    source_name = asset.storage_key or urlparse(asset.uri).path or "asset.bin"
    name_hint = Path(source_name).name or "asset.bin"
    dest = tmp_dir / name_hint
    if asset.storage_key and storage is not None:
        try:
            return await storage.materialize_to_path(asset.storage_key, dest)
        except Exception:
            pass
    local_candidate = _local_path_from_uri(asset.uri)
    if local_candidate is not None:
        return local_candidate
    if storage is not None and asset.storage_key:
        data = await storage.get_bytes(asset.storage_key)
        dest.write_bytes(data)
        return dest
    raise RasterAssetUnavailableError(
        f"Raster asset '{asset.asset_id}' could not be materialized from storage."
    )


def _match_variable_name(candidates: list[str], requested: str) -> str | None:
    req_low = requested.strip().lower()
    for name in candidates:
        if name.lower() == req_low:
            return name
    for name in candidates:
        leaf = name.rsplit("/", 1)[-1].lower()
        if leaf == req_low:
            return name
    for name in candidates:
        low = name.lower()
        if low.endswith(f" {req_low}") or low.endswith(f"/{req_low}"):
            return name
    return None


def _merge_dataset_variable_spec(
    matched: str,
    decoded_spec: VariableSpec,
    dataset: SpatialDataset,
    preferred_ds_var: str | None = None,
) -> VariableSpec:
    ds_spec = dataset.variables.get(preferred_ds_var) if preferred_ds_var else None
    if ds_spec is None:
        ds_match = _match_variable_name(list(dataset.variables.keys()), matched)
        if ds_match is not None:
            ds_spec = dataset.variables[ds_match]
    if ds_spec is None:
        quant_ds_vars = [
            spec
            for spec in dataset.variables.values()
            if spec.semantics not in ("qa_flag", "categorical", "coordinate")
        ]
        if len(quant_ds_vars) == 1:
            ds_spec = quant_ds_vars[0]
    if ds_spec is None:
        return decoded_spec
    resolved_units = (
        ds_spec.units
        if decoded_spec.units in ("1", "dimensionless", "unknown") and ds_spec.units
        else decoded_spec.units
    )
    return replace(
        decoded_spec,
        units=resolved_units,
        nodata=decoded_spec.nodata if decoded_spec.nodata is not None else ds_spec.nodata,
        scale_factor=(
            decoded_spec.scale_factor
            if decoded_spec.scale_factor is not None
            else ds_spec.scale_factor
        ),
        add_offset=(
            decoded_spec.add_offset if decoded_spec.add_offset is not None else ds_spec.add_offset
        ),
        valid_range=(
            decoded_spec.valid_range
            if decoded_spec.valid_range is not None
            else ds_spec.valid_range
        ),
    )


def _select_raster_variable(
    decoded: DecodedDataset,
    dataset: SpatialDataset,
    variable: str | None,
) -> tuple[str, VariableSpec]:
    quant_names = [
        name
        for name, spec in decoded.variables.items()
        if spec.semantics not in ("qa_flag", "categorical", "coordinate")
        and name in decoded.arrays
        and not any(tok in name.rsplit("/", 1)[-1].lower() for tok in _QA_TOKENS)
    ]
    all_names = [name for name in decoded.variables if name in decoded.arrays]
    if variable is not None:
        matched = _match_variable_name(quant_names, variable) or _match_variable_name(
            all_names, variable
        )
        if matched is None:
            raise RasterVariableNotFoundError(
                f"Variable '{variable}' not found in raster asset (available: {all_names})."
            )
        return matched, _merge_dataset_variable_spec(
            matched, decoded.variables[matched], dataset, variable
        )

    for ds_var in dataset.variables:
        matched = _match_variable_name(quant_names, ds_var)
        if matched is not None:
            return matched, _merge_dataset_variable_spec(
                matched, decoded.variables[matched], dataset, ds_var
            )

    if quant_names:
        first = quant_names[0]
        return first, _merge_dataset_variable_spec(first, decoded.variables[first], dataset)
    raise RasterVariableNotFoundError("No continuous scientific raster variable found in asset.")


def _find_qa_variable(
    decoded: DecodedDataset,
    product: str,
    target_var: str,
    target_shape: tuple[int, int],
) -> str | None:
    preferred: tuple[str, ...]
    upper = product.upper()
    if "MOD13" in upper:
        preferred = (
            "250m 16 days pixel reliability",
            "pixel_reliability",
            "250m 16 days VI Quality",
        )
    elif "MOD11" in upper:
        preferred = (
            ("QC_Night", "QC_Day") if "night" in target_var.lower() else ("QC_Day", "QC_Night")
        )
    elif "IMERG" in upper:
        preferred = ("precipitationQualityIndex", "Grid/precipitationQualityIndex")
    elif "SPL3SMP" in upper:
        preferred = (
            "retrieval_qual_flag",
            "Soil_Moisture_Retrieval_Data_AM/retrieval_qual_flag",
            "surface_flag",
        )
    else:
        preferred = ()

    for key in preferred:
        if key in decoded.arrays:
            arr = np.asarray(decoded.arrays[key])
            if arr.shape[-2:] == target_shape:
                return key

    for name, spec in decoded.variables.items():
        if spec.semantics == "qa_flag" and name in decoded.arrays:
            arr = np.asarray(decoded.arrays[name])
            if arr.shape[-2:] == target_shape:
                return name
    return None


def _should_convert_kelvin_to_celsius(
    spec: VariableSpec,
    dataset: SpatialDataset,
    colormap: str | None,
    unit_conversion: str | None,
    sample_values: NDArray[np.float64] | None = None,
) -> bool:
    if unit_conversion == "kelvin_to_celsius":
        if sample_values is not None and sample_values.size > 0:
            return float(np.nanmean(sample_values)) > 150.0
        return "c" not in spec.units.lower()
    if colormap == "lst_celsius":
        units_low = spec.units.strip().lower()
        ds_units = dataset.units.get(spec.name, spec.units).strip().lower()
        is_kelvin = units_low in {"k", "kelvin"} or ds_units in {"k", "kelvin"}
        if is_kelvin:
            if sample_values is not None and sample_values.size > 0:
                return float(np.nanmean(sample_values)) > 150.0
            return True
    return False


def _colorize_values(
    values: NDArray[np.float64],
    valid_mask: NDArray[np.bool_],
    *,
    colormap: str,
    vmin: float | None,
    vmax: float | None,
) -> NDArray[np.uint8]:
    default_min, default_max, stops = _COLOR_RAMPS.get(colormap, _COLOR_RAMPS["viridis"])
    lo = default_min if vmin is None else float(vmin)
    hi = default_max if vmax is None else float(vmax)
    if hi <= lo:
        hi = lo + 1e-6

    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if not np.any(valid_mask):
        return rgba

    stop_t = np.array([s[0] for s in stops], dtype=np.float64)
    stop_r = np.array([s[1][0] for s in stops], dtype=np.float64)
    stop_g = np.array([s[1][1] for s in stops], dtype=np.float64)
    stop_b = np.array([s[1][2] for s in stops], dtype=np.float64)

    norm = np.clip((values[valid_mask] - lo) / (hi - lo), 0.0, 1.0)
    r = np.round(np.interp(norm, stop_t, stop_r)).astype(np.uint8)
    g = np.round(np.interp(norm, stop_t, stop_g)).astype(np.uint8)
    b = np.round(np.interp(norm, stop_t, stop_b)).astype(np.uint8)

    rgba[valid_mask, 0] = r
    rgba[valid_mask, 1] = g
    rgba[valid_mask, 2] = b
    rgba[valid_mask, 3] = 255
    return rgba


def _slice_2d_and_spec(
    raw_arr: NDArray[np.generic],
    spec: VariableSpec,
    step_idx: int,
) -> tuple[NDArray[np.generic], VariableSpec]:
    if raw_arr.ndim < 2:
        raise UnsupportedRasterFormatError(
            f"Variable '{spec.name}' is {raw_arr.ndim}D and cannot be rendered as a 2D map raster."
        )
    arr = raw_arr
    dims = spec.dimensions
    while arr.ndim > 2:
        idx = min(step_idx, arr.shape[0] - 1) if arr.shape[0] > 0 else 0
        arr = arr[idx]
        dims = dims[1:] if len(dims) > 2 else ("y", "x")
    if len(dims) != 2:
        dims = ("y", "x")
    return arr, replace(spec, dimensions=dims)


def _render_sync(
    *,
    asset: AssetReference,
    asset_path: Path,
    readers: ReaderRegistry,
    dataset: SpatialDataset,
    dst_bounds: SpatialBounds,
    dst_crs: str,
    width: int,
    height: int,
    step_idx: int,
    variable: str | None,
    colormap: str | None,
    vmin: float | None,
    vmax: float | None,
    unit_conversion: str | None,
) -> bytes:
    if dst_crs == "EPSG:4326":
        aoi_wgs84 = dst_bounds
    else:
        bx = transform_bounds(dst_crs, "EPSG:4326", *dst_bounds.as_tuple(), densify_pts=21)
        aoi_wgs84 = SpatialBounds(bx[0], bx[1], bx[2], bx[3])

    decoded = readers.read_windowed(
        asset,
        asset_path,
        aoi_bounds=aoi_wgs84,
        aoi_crs="EPSG:4326",
        allow_disjoint_fallback=True,
    )
    var_name, spec = _select_raster_variable(decoded, dataset, variable)
    src_grid = spec.grid or decoded.grid or dataset.spatial_metadata.grid
    if src_grid is None:
        raise IncompatibleDatasetError(f"Raster variable '{var_name}' lacks spatial grid metadata.")

    raw_arr = np.asarray(decoded.arrays[var_name])
    slice_arr, render_spec = _slice_2d_and_spec(raw_arr, spec, step_idx)

    dst_grid = GridSpec(
        crs=dst_crs,
        resolution_x=(dst_bounds.max_x - dst_bounds.min_x) / float(width),
        resolution_y=(dst_bounds.max_y - dst_bounds.min_y) / float(height),
        resolution_unit="degree" if "4326" in dst_crs else "meter",
        bounds=dst_bounds,
        width=width,
        height=height,
        pixel_convention="corner",
    )

    try:
        warped, _ = warp_variable(
            slice_arr,
            render_spec,
            src_grid,
            dst_grid,
            "nearest",
            decoded.coordinates,
        )
    except (IncompatibleDatasetError, WindowError, ValueError):
        return _transparent_png(width, height)

    data = warped.data.astype(np.float64, copy=False)
    valid = np.isfinite(data)
    if render_spec.valid_range is not None:
        lo, hi = render_spec.valid_range
        valid &= (data >= lo) & (data <= hi)

    valid_samples = data[valid]
    if _should_convert_kelvin_to_celsius(
        render_spec, dataset, colormap, unit_conversion, valid_samples
    ):
        data = np.where(valid, data - 273.15, np.nan)

    ramp_name = colormap or "viridis"
    rgba = _colorize_values(data, valid, colormap=ramp_name, vmin=vmin, vmax=vmax)
    return encode_rgba_png(rgba)


async def render_dataset_tile(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    z: int,
    x: int,
    y: int,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> bytes:
    """Render an XYZ 256x256 PNG tile for a persisted raster dataset."""
    asset, step_idx = _select_raster_asset(dataset, timestamp=timestamp, variable=variable)
    tile_3857 = tile_bounds_3857(z, x, y)
    ds_wgs84 = _dataset_wgs84_bounds(dataset)
    if ds_wgs84 is not None:
        ds_3857 = tuple(
            float(v) for v in transform_bounds("EPSG:4326", "EPSG:3857", *ds_wgs84, densify_pts=21)
        )
        if not _bounds_intersect(tile_3857, (ds_3857[0], ds_3857[1], ds_3857[2], ds_3857[3])):
            return _transparent_png(256, 256)

    dst_bounds = SpatialBounds(*tile_3857)
    with tempfile.TemporaryDirectory(prefix="ghs-tile-") as tmp_root:
        local_path = await _materialize_asset(asset, storage, Path(tmp_root))
        return await asyncio.to_thread(
            _render_sync,
            asset=asset,
            asset_path=local_path,
            readers=readers,
            dataset=dataset,
            dst_bounds=dst_bounds,
            dst_crs="EPSG:3857",
            width=256,
            height=256,
            step_idx=step_idx,
            variable=variable,
            colormap=colormap,
            vmin=vmin,
            vmax=vmax,
            unit_conversion=unit_conversion,
        )


async def render_dataset_bbox(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    bbox: tuple[float, float, float, float],
    crs: str = "EPSG:4326",
    width: int = 512,
    height: int = 512,
    variable: str | None = None,
    timestamp: str | None = None,
    colormap: str | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    unit_conversion: str | None = None,
) -> bytes:
    """Render a georeferenced RGBA PNG image for a bounding box over a raster dataset."""
    asset, step_idx = _select_raster_asset(dataset, timestamp=timestamp, variable=variable)
    dst_bounds = SpatialBounds(*bbox)
    with tempfile.TemporaryDirectory(prefix="ghs-bbox-") as tmp_root:
        local_path = await _materialize_asset(asset, storage, Path(tmp_root))
        return await asyncio.to_thread(
            _render_sync,
            asset=asset,
            asset_path=local_path,
            readers=readers,
            dataset=dataset,
            dst_bounds=dst_bounds,
            dst_crs=crs,
            width=width,
            height=height,
            step_idx=step_idx,
            variable=variable,
            colormap=colormap,
            vmin=vmin,
            vmax=vmax,
            unit_conversion=unit_conversion,
        )


def _evaluate_qa_pass(product: str, qa_code: int) -> bool | None:
    upper = product.upper()
    if "MOD13" in upper:
        return qa_code in (0, 1)
    if "MOD11" in upper:
        mandatory = qa_code & 0b11
        err_bits = (qa_code >> 6) & 0b11
        return mandatory <= 1 and err_bits <= 1
    if "SPL3SMP" in upper:
        return (qa_code & 0b1) == 0
    return None


def _point_query_sync(
    *,
    asset: AssetReference,
    asset_path: Path,
    readers: ReaderRegistry,
    dataset: SpatialDataset,
    lon: float,
    lat: float,
    step_idx: int,
    variable: str | None,
    timestamp: str | None,
    unit_conversion: str | None,
) -> dict[str, Any]:
    eps = 0.05
    aoi_wgs84 = SpatialBounds(
        max(-180.0, lon - eps),
        max(-90.0, lat - eps),
        min(180.0, lon + eps),
        min(90.0, lat + eps),
    )
    decoded = readers.read_windowed(
        asset,
        asset_path,
        aoi_bounds=aoi_wgs84,
        aoi_crs="EPSG:4326",
        allow_disjoint_fallback=True,
    )
    var_name, spec = _select_raster_variable(decoded, dataset, variable)
    src_grid = spec.grid or decoded.grid or dataset.spatial_metadata.grid
    if src_grid is None:
        raise IncompatibleDatasetError(f"Raster variable '{var_name}' lacks spatial grid metadata.")

    raw_arr = np.asarray(decoded.arrays[var_name])
    slice_arr, slice_spec = _slice_2d_and_spec(raw_arr, spec, step_idx)
    oriented, _ = orient_to_north_up(slice_arr, slice_spec.dimensions, decoded.coordinates)
    src_res = src_grid.resolved()
    aff = to_rasterio_affine(src_res)

    if "4326" in src_res.crs:
        x_nat, y_nat = lon, lat
    else:
        tx = Transformer.from_crs("EPSG:4326", src_res.crs, always_xy=True)
        x_nat, y_nat = tx.transform(lon, lat)

    col_f, row_f = (~aff) * (x_nat, y_nat)
    col, row = math.floor(col_f), math.floor(row_f)

    ds_bbox = _dataset_wgs84_bounds(dataset) or (-180.0, -90.0, 180.0, 90.0)
    ts_list = _extract_timestamps_list(dataset, var_name)
    fallback_ts = dataset.temporal_metadata.start.isoformat()
    active_ts = timestamp or (ts_list[step_idx] if step_idx < len(ts_list) else fallback_ts)

    time_series_pts: list[dict[str, Any]] = []
    ts_ext = dataset.extensions.get("time_series")
    if isinstance(ts_ext, Mapping):
        ts_entry = ts_ext.get(var_name)
        if ts_entry is None:
            for k, v in ts_ext.items():
                if _match_variable_name([str(k)], var_name) or _match_variable_name(
                    [var_name], str(k)
                ):
                    ts_entry = v
                    break
        if ts_entry is None and len(ts_ext) == 1:
            ts_entry = next(iter(ts_ext.values()))
        if isinstance(ts_entry, Mapping):
            e_ts = ts_entry.get("timestamps") or []
            e_vals = ts_entry.get("values") or []
            for t_str, t_val in zip(e_ts, e_vals, strict=False):
                time_series_pts.append({"timestamp": str(t_str), "value": t_val})

    base_resp: dict[str, Any] = {
        "dataset_id": dataset.dataset_id,
        "product": dataset.product,
        "variable": var_name,
        "lon": lon,
        "lat": lat,
        "timestamp": active_ts,
        "crs": src_res.crs,
        "nominal_resolution_m": (
            float(src_res.resolution_x) if "4326" not in src_res.crs else None
        ),
        "bbox": {
            "min_lon": ds_bbox[0],
            "min_lat": ds_bbox[1],
            "max_lon": ds_bbox[2],
            "max_lat": ds_bbox[3],
        },
        "time_series": time_series_pts,
    }

    if row < 0 or row >= oriented.shape[0] or col < 0 or col >= oriented.shape[1]:
        return {
            **base_resp,
            "status": "outside_bounds",
            "value": None,
            "raw_value": None,
            "unit": dataset.units.get(var_name, spec.units),
            "qa_value": None,
            "qa_passed": None,
            "pixel_row": None,
            "pixel_col": None,
        }

    raw_scalar = float(oriented[row, col])
    qa_var = _find_qa_variable(
        decoded, dataset.product, var_name, (oriented.shape[0], oriented.shape[1])
    )
    qa_val: int | None = None
    qa_passed: bool | None = None
    if qa_var is not None:
        qa_raw = np.asarray(decoded.arrays[qa_var])
        qa_slice, qa_spec = _slice_2d_and_spec(qa_raw, decoded.variables[qa_var], step_idx)
        qa_oriented, _ = orient_to_north_up(qa_slice, qa_spec.dimensions, decoded.coordinates)
        qa_val = int(qa_oriented[row, col])
        qa_passed = _evaluate_qa_pass(dataset.product, qa_val)

    is_nodata = not math.isfinite(raw_scalar)
    if not is_nodata and spec.nodata is not None:
        nd = float(spec.nodata)
        is_nodata = math.isnan(nd) if math.isnan(raw_scalar) else raw_scalar == nd

    unit_out = dataset.units.get(var_name, spec.units)
    if is_nodata:
        return {
            **base_resp,
            "status": "nodata",
            "value": None,
            "raw_value": raw_scalar if math.isfinite(raw_scalar) else None,
            "unit": unit_out,
            "qa_value": qa_val,
            "qa_passed": qa_passed,
            "pixel_row": row,
            "pixel_col": col,
        }

    scale = spec.scale_factor if spec.scale_factor is not None else 1.0
    offset = spec.add_offset if spec.add_offset is not None else 0.0
    phys = raw_scalar * scale + offset

    if spec.valid_range is not None:
        lo, hi = spec.valid_range
        if phys < lo or phys > hi:
            return {
                **base_resp,
                "status": "nodata",
                "value": None,
                "raw_value": raw_scalar,
                "unit": unit_out,
                "qa_value": qa_val,
                "qa_passed": qa_passed,
                "pixel_row": row,
                "pixel_col": col,
            }

    if _should_convert_kelvin_to_celsius(
        spec, dataset, None, unit_conversion, np.array([phys], dtype=np.float64)
    ):
        phys -= 273.15
        unit_out = "°C"

    return {
        **base_resp,
        "status": "ok",
        "value": float(phys),
        "raw_value": raw_scalar,
        "unit": unit_out,
        "qa_value": qa_val,
        "qa_passed": qa_passed,
        "pixel_row": row,
        "pixel_col": col,
    }


async def query_dataset_point(
    dataset: SpatialDataset,
    storage: StoragePort | None,
    readers: ReaderRegistry,
    *,
    lon: float,
    lat: float,
    variable: str | None = None,
    timestamp: str | None = None,
    unit_conversion: str | None = None,
) -> dict[str, Any]:
    """Sample exact native grid pixel value and QA metadata at WGS 84 (lon, lat)."""
    asset, step_idx = _select_raster_asset(dataset, timestamp=timestamp, variable=variable)
    with tempfile.TemporaryDirectory(prefix="ghs-pt-") as tmp_root:
        local_path = await _materialize_asset(asset, storage, Path(tmp_root))
        return await asyncio.to_thread(
            _point_query_sync,
            asset=asset,
            asset_path=local_path,
            readers=readers,
            dataset=dataset,
            lon=lon,
            lat=lat,
            step_idx=step_idx,
            variable=variable,
            timestamp=timestamp,
            unit_conversion=unit_conversion,
        )
