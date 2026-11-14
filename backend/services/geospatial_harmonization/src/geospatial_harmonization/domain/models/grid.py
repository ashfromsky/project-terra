"""Grid specification domain models with mutual consistency validation."""

import math
from dataclasses import dataclass, replace
from typing import Literal

from geospatial_harmonization.domain.exceptions import InvalidGridSpecError

ResolutionUnit = Literal["meter", "degree", "arcsecond"]
GridAlignmentPolicy = Literal["bounds_origin", "explicit_transform"]
PixelConvention = Literal["corner", "center"]

_GRID_REL_TOL = 1e-6


def _require_finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise InvalidGridSpecError(f"{name} must be finite, got {value!r}")
    return value


def _require_positive(value: float, name: str) -> float:
    _require_finite(value, name)
    if value <= 0.0:
        raise InvalidGridSpecError(f"{name} must be > 0, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class SpatialBounds:
    """Axis-aligned spatial bounding box in the target CRS."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        for name, val in zip(("min_x", "min_y", "max_x", "max_y"), self.as_tuple(), strict=True):
            _require_finite(val, name)
        if self.min_x >= self.max_x:
            raise InvalidGridSpecError(f"min_x ({self.min_x}) must be < max_x ({self.max_x})")
        if self.min_y >= self.max_y:
            raise InvalidGridSpecError(f"min_y ({self.min_y}) must be < max_y ({self.max_y})")

    @property
    def width_span(self) -> float:
        return self.max_x - self.min_x

    @property
    def height_span(self) -> float:
        return self.max_y - self.min_y

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.min_x, self.min_y, self.max_x, self.max_y)


@dataclass(frozen=True, slots=True)
class AffineMatrix:
    """Six-parameter 2D affine geotransform independent of concrete raster libraries."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def __post_init__(self) -> None:
        for name, val in zip(("a", "b", "c", "d", "e", "f"), self.to_tuple(), strict=True):
            _require_finite(val, f"transform.{name}")
        if math.isclose(self.a * self.e - self.b * self.d, 0.0, abs_tol=1e-15):
            raise InvalidGridSpecError("AffineMatrix determinant must be non-zero")

    @classmethod
    def north_up(
        cls,
        bounds: SpatialBounds,
        resolution_x: float,
        resolution_y: float,
        pixel_convention: PixelConvention = "corner",
    ) -> "AffineMatrix":
        offset_x = 0.5 * resolution_x if pixel_convention == "center" else 0.0
        offset_y = 0.5 * resolution_y if pixel_convention == "center" else 0.0
        return cls(
            a=resolution_x,
            b=0.0,
            c=bounds.min_x + offset_x,
            d=0.0,
            e=-resolution_y,
            f=bounds.max_y - offset_y,
        )

    def to_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.a, self.b, self.c, self.d, self.e, self.f)


@dataclass(frozen=True, slots=True)
class GridSpec:
    """Complete, mutually validated spatial grid definition."""

    crs: str
    resolution_x: float
    resolution_y: float
    resolution_unit: ResolutionUnit
    bounds: SpatialBounds
    width: int | None = None
    height: int | None = None
    transform: AffineMatrix | None = None
    alignment_policy: GridAlignmentPolicy = "bounds_origin"
    pixel_convention: PixelConvention = "corner"

    def __post_init__(self) -> None:
        if not self.crs.strip():
            raise InvalidGridSpecError("crs must be a non-empty CRS identifier or WKT string")
        _require_positive(self.resolution_x, "resolution_x")
        _require_positive(self.resolution_y, "resolution_y")

        if self.alignment_policy == "explicit_transform":
            if self.transform is None or self.width is None or self.height is None:
                raise InvalidGridSpecError(
                    "alignment_policy='explicit_transform' requires transform, width, and height"
                )
            if self.width <= 0 or self.height <= 0:
                raise InvalidGridSpecError("width and height must be > 0")
            return

        expected_w = self._derive_dimension(self.bounds.width_span, self.resolution_x, "x")
        expected_h = self._derive_dimension(self.bounds.height_span, self.resolution_y, "y")
        self._validate_dimension(self.width, expected_w, "width")
        self._validate_dimension(self.height, expected_h, "height")
        if self.transform is not None:
            self._validate_transform(self.transform)

    @staticmethod
    def _validate_dimension(actual: int | None, expected: int, label: str) -> None:
        if actual is None:
            return
        if actual <= 0:
            raise InvalidGridSpecError(f"{label} must be > 0, got {actual}")
        if actual != expected:
            raise InvalidGridSpecError(
                f"{label} ({actual}) is inconsistent with bounds and resolution "
                f"(expected {expected})"
            )

    @staticmethod
    def _derive_dimension(span: float, resolution: float, axis: str) -> int:
        raw = span / resolution
        rounded = round(raw)
        if rounded < 1 or not math.isclose(raw, rounded, rel_tol=_GRID_REL_TOL, abs_tol=1e-9):
            raise InvalidGridSpecError(
                f"Bounds {axis}-span ({span}) is not an integer multiple "
                f"of resolution ({resolution})"
            )
        return int(rounded)

    def _validate_transform(self, transform: AffineMatrix) -> None:
        if self.alignment_policy == "explicit_transform":
            return
        expected = AffineMatrix.north_up(
            self.bounds, self.resolution_x, self.resolution_y, self.pixel_convention
        )
        for name, actual, target in zip(
            ("a", "b", "c", "d", "e", "f"),
            transform.to_tuple(),
            expected.to_tuple(),
            strict=True,
        ):
            if not math.isclose(actual, target, rel_tol=_GRID_REL_TOL, abs_tol=1e-9):
                raise InvalidGridSpecError(
                    f"transform.{name} ({actual}) conflicts with grid definition ({target})"
                )

    def resolved(self) -> "GridSpec":
        """Return a GridSpec with omitted dimensions and affine transform derived."""
        return replace(
            self,
            width=self.width
            if self.width is not None
            else self._derive_dimension(self.bounds.width_span, self.resolution_x, "x"),
            height=self.height
            if self.height is not None
            else self._derive_dimension(self.bounds.height_span, self.resolution_y, "y"),
            transform=self.transform
            if self.transform is not None
            else AffineMatrix.north_up(
                self.bounds, self.resolution_x, self.resolution_y, self.pixel_convention
            ),
        )

    @property
    def pixel_count(self) -> int:
        resolved = self.resolved()
        assert resolved.width is not None and resolved.height is not None
        return resolved.width * resolved.height
