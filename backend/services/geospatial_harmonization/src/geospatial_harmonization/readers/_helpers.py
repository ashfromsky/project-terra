"""Shared format-neutral helpers for building DecodedDataset contracts."""

import math
from collections.abc import Iterable, Mapping

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
    lower = name.lower()
    if lower in _COORD_NAMES:
        return "coordinate"
    if not is_numeric:
        return "categorical"
    if any(k in attrs for k in ("flag_values", "flag_masks", "flag_meanings")) or any(
        token in lower for token in _QA_MARKERS
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


def as_float(value: object) -> float | None:
    """Convert numeric scalars cleanly to float without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
