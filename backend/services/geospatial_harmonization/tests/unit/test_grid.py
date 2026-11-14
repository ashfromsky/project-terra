"""Unit tests for SpatialBounds, AffineMatrix, and GridSpec domain invariants."""

import pytest

from geospatial_harmonization.domain import (
    AffineMatrix,
    GridSpec,
    InvalidGridSpecError,
    SpatialBounds,
)


def test_gridspec_derives_dimensions_and_corner_transform_deterministically() -> None:
    bounds = SpatialBounds(min_x=-10.0, min_y=40.0, max_x=10.0, max_y=50.0)
    spec = GridSpec(
        crs="EPSG:4326",
        resolution_x=0.5,
        resolution_y=0.25,
        resolution_unit="degree",
        bounds=bounds,
    )

    resolved = spec.resolved()

    assert spec.width is None
    assert spec.transform is None
    assert resolved.width == 40
    assert resolved.height == 40
    assert resolved.pixel_count == 1600
    assert resolved.transform == AffineMatrix(a=0.5, b=0.0, c=-10.0, d=0.0, e=-0.25, f=50.0)


def test_gridspec_center_convention_offsets_transform_origin_by_half_pixel() -> None:
    bounds = SpatialBounds(min_x=0.0, min_y=0.0, max_x=1000.0, max_y=2000.0)
    spec = GridSpec(
        crs="EPSG:6933",
        resolution_x=250.0,
        resolution_y=500.0,
        resolution_unit="meter",
        bounds=bounds,
        pixel_convention="center",
    ).resolved()

    assert spec.width == 4
    assert spec.height == 4
    assert spec.transform == AffineMatrix(a=250.0, b=0.0, c=125.0, d=0.0, e=-500.0, f=1750.0)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"min_x": 10.0, "max_x": 10.0}, "must be <"),
        ({"min_y": float("nan")}, "must be finite"),
    ],
)
def test_spatial_bounds_reject_invalid_coordinates(kwargs: dict[str, float], match: str) -> None:
    base = {"min_x": 0.0, "min_y": 0.0, "max_x": 10.0, "max_y": 10.0}
    base.update(kwargs)
    with pytest.raises(InvalidGridSpecError, match=match):
        SpatialBounds(**base)


def test_gridspec_rejects_inconsistent_dimensions_and_transforms() -> None:
    bounds = SpatialBounds(min_x=0.0, min_y=0.0, max_x=10.0, max_y=10.0)

    with pytest.raises(InvalidGridSpecError, match="inconsistent"):
        GridSpec(
            crs="EPSG:4326",
            resolution_x=1.0,
            resolution_y=1.0,
            resolution_unit="degree",
            bounds=bounds,
            width=12,
            height=10,
        )

    with pytest.raises(InvalidGridSpecError, match="not an integer multiple"):
        GridSpec(
            crs="EPSG:4326",
            resolution_x=3.0,
            resolution_y=1.0,
            resolution_unit="degree",
            bounds=bounds,
        )

    with pytest.raises(InvalidGridSpecError, match=r"transform\.c"):
        GridSpec(
            crs="EPSG:4326",
            resolution_x=1.0,
            resolution_y=1.0,
            resolution_unit="degree",
            bounds=bounds,
            transform=AffineMatrix(a=1.0, b=0.0, c=2.0, d=0.0, e=-1.0, f=10.0),
        )

    with pytest.raises(InvalidGridSpecError, match="requires transform, width, and height"):
        GridSpec(
            crs="EPSG:4326",
            resolution_x=1.0,
            resolution_y=1.0,
            resolution_unit="degree",
            bounds=bounds,
            alignment_policy="explicit_transform",
        )


def test_gridspec_accepts_rotated_explicit_transform() -> None:
    rotated = GridSpec(
        crs="EPSG:32631",
        resolution_x=10.0,
        resolution_y=10.0,
        resolution_unit="meter",
        bounds=SpatialBounds(min_x=0.0, min_y=0.0, max_x=115.0, max_y=115.0),
        width=10,
        height=10,
        transform=AffineMatrix(a=8.0, b=6.0, c=0.0, d=6.0, e=-8.0, f=100.0),
        alignment_policy="explicit_transform",
    )
    assert rotated.pixel_count == 100


def test_affine_matrix_rejects_singular_matrix() -> None:
    with pytest.raises(InvalidGridSpecError, match="determinant"):
        AffineMatrix(a=0.0, b=0.0, c=0.0, d=0.0, e=-1.0, f=10.0)
