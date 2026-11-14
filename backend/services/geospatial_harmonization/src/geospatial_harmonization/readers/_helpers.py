"""Shared format-neutral helpers for building DecodedDataset contracts."""

import math
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
from pyproj import CRS

from geospatial_harmonization.domain.models.dataset import VariableSemantics
from geospatial_harmonization.domain.models.grid import (
    AffineMatrix,
    GridAlignmentPolicy,
    GridSpec,
    ResolutionUnit,
    SpatialBounds,
)
from geospatial_harmonization.readers.registry import AssetDecodeError

_QA_MARKERS = ("qa", "qc", "qual", "flag", "bitmask", "reliability")
_COORD_NAMES = frozenset({"lat", "latitude", "lon", "longitude", "x", "y", "time"})


def canonical_crs_string(raw_crs: object) -> str | None:
    """Normalize a CRS object or string into an authority code or WKT2 string."""
    if raw_crs is None:
        return None
    text = raw_crs.to_wkt() if hasattr(raw_crs, "to_wkt") else str(raw_crs).strip()
    if not text:
        return None
    try:
        crs = CRS.from_user_input(text)
    except Exception:
        return text
    auth = crs.to_authority()
    return f"{auth[0]}:{auth[1]}" if auth is not None else crs.to_wkt()


def resolution_unit_from_crs(crs_str: str) -> ResolutionUnit:
    """Infer spatial resolution unit from pyproj axis metadata without PROJ4 fallback."""
    crs = CRS.from_user_input(crs_str)
    if crs.axis_info:
        unit = crs.axis_info[0].unit_name.lower()
        if "degree" in unit:
            return "degree"
        if "second" in unit:
            return "arcsecond"
        if "met" in unit:
            return "meter"
    return "degree" if crs.is_geographic else "meter"


def build_grid_from_affine(
    crs_str: str | None,
    affine: tuple[float, float, float, float, float, float],
    width: int,
    height: int,
) -> tuple[GridSpec | None, tuple[str, ...]]:
    """Construct a validated GridSpec only when georeferencing metadata is present."""
    if crs_str is None:
        return None, ("No explicit CRS metadata found; spatial grid not invented.",)
    a, b, c, d, e, f = (float(v) for v in affine)
    if (a, b, c, d, e, f) == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0):
        return None, ("Identity pixel transform found without georeferencing; grid skipped.",)
    if width <= 0 or height <= 0 or math.isclose(a * e - b * d, 0.0, abs_tol=1e-15):
        return None, ("Degenerate affine transform or dimensions; grid skipped.",)

    xs = [c, a * width + c, b * height + c, a * width + b * height + c]
    ys = [f, d * width + f, e * height + f, d * width + e * height + f]
    bounds = SpatialBounds(min(xs), min(ys), max(xs), max(ys))
    north_up = b == 0.0 and d == 0.0 and a > 0.0 and e < 0.0
    policy: GridAlignmentPolicy = "bounds_origin" if north_up else "explicit_transform"
    grid = GridSpec(
        crs=crs_str,
        resolution_x=math.hypot(a, d),
        resolution_y=math.hypot(b, e),
        resolution_unit=resolution_unit_from_crs(crs_str),
        bounds=bounds,
        width=width,
        height=height,
        transform=AffineMatrix(a, b, c, d, e, f),
        alignment_policy=policy,
    )
    return grid, ()


def infer_variable_semantics(
    name: str, attrs: Mapping[str, object], is_numeric: bool = True
) -> VariableSemantics:
    """Classify variable physical/QA semantics from metadata attributes and naming."""
    leaf = name.rsplit("/", 1)[-1].lower()
    if leaf in _COORD_NAMES:
        return "coordinate"
    if not is_numeric:
        return "categorical"
    if any(k in attrs for k in ("flag_values", "flag_masks", "flag_meanings")) or any(
        token in leaf for token in _QA_MARKERS
    ):
        return "qa_flag"
    if "sum" in str(attrs.get("cell_methods", "")).lower():
        return "continuous_extensive"
    return "continuous_intensive"


def select_variables(
    available: Iterable[str], requested: tuple[str, ...] | None
) -> tuple[str, ...]:
    """Filter variable names lazily while failing explicitly on missing requested fields."""
    avail = tuple(available)
    if requested is None:
        return avail
    missing = [v for v in requested if v not in avail]
    if missing:
        raise AssetDecodeError(f"Requested variables not found in asset: {missing}")
    return tuple(v for v in avail if v in requested)


def to_python_scalar(value: object) -> object:
    """Convert numpy/bytes scalar metadata cleanly to native JSON-safe Python types."""
    if isinstance(value, np.ndarray):
        return [to_python_scalar(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return to_python_scalar(value.item())
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def to_attr_dict(items: Iterable[tuple[str, object]]) -> dict[str, object]:
    """Normalize an attribute stream into native Python types."""
    return {str(k): to_python_scalar(v) for k, v in items}


def as_float(value: object) -> float | None:
    """Convert numeric scalars cleanly to float without accepting booleans."""
    native = to_python_scalar(value)
    if isinstance(native, bool) or not isinstance(native, (int, float)):
        return None
    f = float(native)
    return f if math.isfinite(f) else None


def extract_cf_var_meta(
    name: str, attrs: Mapping[str, object], is_numeric: bool = True
) -> tuple[VariableSemantics, float | None, float | None, float | int | None, list[str]]:
    """Extract variable semantics, CF scaling, and nodata without scaling QA/categorical fields."""
    semantics = infer_variable_semantics(name, attrs, is_numeric=is_numeric)
    raw_nodata = attrs.get("_FillValue", attrs.get("missing_value"))
    native_nd = to_python_scalar(raw_nodata)
    nodata = (
        native_nd
        if isinstance(native_nd, (int, float)) and not isinstance(native_nd, bool)
        else None
    )
    scale = as_float(attrs.get("scale_factor"))
    offset = as_float(attrs.get("add_offset"))
    scale = None if scale == 1.0 else scale
    offset = None if offset == 0.0 else offset
    warnings: list[str] = []
    if semantics in ("qa_flag", "categorical") and (scale is not None or offset is not None):
        warnings.append(f"Dropped scaling on '{name}' ({semantics})")
        return semantics, None, None, nodata, warnings
    return semantics, scale, offset, nodata, warnings


def _uniform_step(coords: Sequence[float]) -> float | None:
    if len(coords) < 2:
        return None
    diffs = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
    step = (coords[-1] - coords[0]) / (len(coords) - 1)
    if math.isclose(step, 0.0, abs_tol=1e-12):
        return None
    if all(math.isclose(d, step, rel_tol=1e-3, abs_tol=1e-9) for d in diffs):
        return abs(step)
    return None


def grid_from_axes(
    crs_str: str | None, xs: Sequence[float] | None, ys: Sequence[float] | None
) -> tuple[GridSpec | None, tuple[str, ...]]:
    """Infer a center-registered GridSpec from uniform 1D coordinate vectors when CRS exists."""
    if crs_str is None:
        return None, ("No explicit CRS metadata found; spatial grid not invented.",)
    if xs is None or ys is None:
        return None, ("Missing 1D spatial coordinate vectors; grid skipped.",)
    dx, dy = _uniform_step(xs), _uniform_step(ys)
    if dx is None or dy is None:
        return None, ("Non-uniform or insufficient 1D coordinates; regular grid skipped.",)
    bounds = SpatialBounds(
        min(xs) - 0.5 * dx, min(ys) - 0.5 * dy, max(xs) + 0.5 * dx, max(ys) + 0.5 * dy
    )
    return (
        GridSpec(
            crs=crs_str,
            resolution_x=dx,
            resolution_y=dy,
            resolution_unit=resolution_unit_from_crs(crs_str),
            bounds=bounds,
            width=len(xs),
            height=len(ys),
            pixel_convention="center",
        ),
        (),
    )
