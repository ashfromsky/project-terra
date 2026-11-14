"""Unit tests for QualityPolicy and QualityValidator gate checks."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from geospatial_harmonization.domain.exceptions import QualityPolicyViolationError
from geospatial_harmonization.domain.models import dataset as dm
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.transformations import QualityPolicy, QualityValidator


def _dataset(
    var_spec: dm.VariableSpec,
    *,
    crs: str | None = "EPSG:3857",
    assets: tuple[dm.AssetReference, ...] = (),
    steps: tuple[str, ...] = ("target_grid_transform",),
) -> dm.SpatialDataset:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    bounds = SpatialBounds(0.0, 0.0, 200.0, 200.0)
    grid = GridSpec(crs, 100.0, 100.0, "meter", bounds).resolved() if crs else None
    return dm.SpatialDataset(
        uuid4(),
        "q-1",
        "generic",
        "prod",
        {var_spec.name: var_spec},
        {var_spec.name: var_spec.units},
        dm.SpatialMetadata("raster", crs, bounds if crs else None, grid),
        TemporalSpec(now, now, "daily", "instantaneous"),
        dm.QualityMetadata("validated", excluded_count=1, exclusion_reasons=("cloud",)),
        assets,
        dm.ProvenanceRecord("generic", "prod", "1.0", now, "0.1.0", processing_steps=steps),
    )


def test_quality_validator_detects_out_of_range_after_scaling_and_enforces() -> None:
    ndvi = dm.VariableSpec(
        "NDVI",
        "1",
        "int16",
        ("y", "x"),
        "continuous_intensive",
        nodata=-3000,
        scale_factor=0.0001,
        valid_range=(-0.2, 1.0),
    )
    ds = _dataset(ndvi)
    raw = np.array([[5000, -3000], [8000, 15000]], dtype=np.int16)

    validator = QualityValidator(QualityPolicy(min_valid_fraction=0.5, fail_on_out_of_range=True))
    report = validator.validate_arrays(ds, {"NDVI": raw}, already_scaled=False)
    assert report.passed is False
    assert report.valid_fraction == pytest.approx(0.75)
    assert any("outside valid_range" in err for err in report.errors)
    assert any("excluded observations" in w for w in report.warnings)

    with pytest.raises(QualityPolicyViolationError, match="outside valid_range"):
        validator.enforce(report)

    lenient = QualityValidator(QualityPolicy(min_valid_fraction=0.5, fail_on_out_of_range=False))
    warn_report = lenient.validate_arrays(ds, {"NDVI": raw}, already_scaled=False)
    assert warn_report.passed is True
    assert any("outside valid_range" in w for w in warn_report.warnings)


def test_quality_validator_checks_insufficient_data_crs_and_geotiff_assets(tmp_path: Path) -> None:
    tif = tmp_path / "band.tif"
    arr = np.array([[295.0, -999.0], [300.0, 305.0]], dtype=np.float32)
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, 200.0, 100.0, 100.0),
        nodata=-999.0,
    ) as dst:
        dst.write(arr, 1)
        dst.set_band_description(1, "T")

    spec = dm.VariableSpec(
        "T", "K", "float32", ("y", "x"), "continuous_intensive", -999.0, valid_range=(200.0, 350.0)
    )
    asset = dm.AssetReference("b1", tif.as_uri(), "geotiff", "image/tiff")
    ds = _dataset(spec, assets=(asset,))

    ok = QualityValidator(
        QualityPolicy(min_valid_fraction=0.5, require_processing_provenance=True)
    ).validate_dataset_assets(ds)
    assert ok.passed is True
    assert ok.valid_fraction == pytest.approx(0.75)

    strict_low = QualityValidator(QualityPolicy(min_valid_fraction=0.9)).validate_dataset_assets(ds)
    assert strict_low.passed is False
    assert any("below policy minimum" in e for e in strict_low.errors)

    no_crs = replace(ds, spatial_metadata=dm.SpatialMetadata("raster", None))
    crs_report = QualityValidator().validate_arrays(no_crs, {"T": arr})
    assert crs_report.passed is False
    assert any("missing explicit CRS" in e for e in crs_report.errors)

    with pytest.raises(QualityPolicyViolationError, match="min_valid_fraction"):
        QualityPolicy(min_valid_fraction=1.2)
