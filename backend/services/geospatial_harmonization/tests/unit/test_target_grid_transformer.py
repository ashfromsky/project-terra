"""Unit tests for provider-agnostic TargetGridTransformer."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import netCDF4
import numpy as np
import pytest

from geospatial_harmonization.domain.models import dataset as dm
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import TargetGridTransformRequest
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.domain.ports import GridTransformer
from geospatial_harmonization.readers import GeoTIFFReader
from geospatial_harmonization.transformations import TargetGridTransformer


def _grid(res: float) -> GridSpec:
    return GridSpec(
        "EPSG:3857",
        res,
        res,
        "meter",
        SpatialBounds(0.0, 0.0, 400.0, 400.0),
        pixel_convention="corner",
    ).resolved()


def test_transform_netcdf_mixed_semantics_conserves_flux_and_raw_immutability(
    tmp_path: Path,
) -> None:
    nc = tmp_path / "raw.nc"
    with netCDF4.Dataset(nc, "w") as ds:
        ds.createDimension("y", 4)
        ds.createDimension("x", 4)
        ds.crs = "EPSG:3857"
        ds.createVariable("y", "f8", ("y",))[:] = np.array([350.0, 250.0, 150.0, 50.0])
        ds.createVariable("x", "f8", ("x",))[:] = np.array([50.0, 150.0, 250.0, 350.0])
        ds.createVariable("temp", "f4", ("y", "x"), fill_value=-9999.0)[:] = np.full(
            (4, 4), 300.0, np.float32
        )
        ds.createVariable("mass", "f4", ("y", "x"), fill_value=-9999.0)[:] = np.ones(
            (4, 4), np.float32
        )
        ds.createVariable("QC", "u1", ("y", "x"), fill_value=255)[:] = np.array(
            [[0, 8, 1, 255], [0, 0, 8, 8], [1, 1, 0, 0], [8, 8, 0, 255]], np.uint8
        )

    digest = hashlib.sha256(nc.read_bytes()).hexdigest()
    src_grid, dst_grid = _grid(100.0), _grid(200.0)
    variables = {
        "temp": dm.VariableSpec(
            "temp", "K", "float32", ("y", "x"), "continuous_intensive", -9999.0
        ),
        "mass": dm.VariableSpec(
            "mass", "kg", "float32", ("y", "x"), "continuous_extensive", -9999.0
        ),
        "QC": dm.VariableSpec("QC", "bitmask", "uint8", ("y", "x"), "qa_flag", 255),
    }
    now = datetime(2026, 6, 1, tzinfo=UTC)
    dataset = dm.SpatialDataset(
        uuid4(),
        "src-001",
        "generic",
        "test_product",
        variables,
        {k: v.units for k, v in variables.items()},
        dm.SpatialMetadata("raster", src_grid.crs, src_grid.bounds, src_grid),
        TemporalSpec(now, now, "daily", "instantaneous"),
        dm.QualityMetadata("raw"),
        (dm.AssetReference("a1", nc.as_uri(), "netcdf", "application/x-netcdf"),),
        dm.ProvenanceRecord("generic", "test_product", "1.0", now, "0.1.0"),
    )

    transformer: GridTransformer = TargetGridTransformer(output_dir=tmp_path / "derived")
    res = transformer.transform(TargetGridTransformRequest(dataset=dataset, target_grid=dst_grid))

    assert hashlib.sha256(nc.read_bytes()).hexdigest() == digest
    assert res.methods_applied == {"temp": "bilinear", "mass": "sum", "QC": "nearest"}
    assert res.quality_report.passed is True and res.dataset.spatial_metadata.grid == dst_grid

    mass_a = next(a for a in res.dataset.assets if a.asset_id.endswith("_mass"))
    mass_dec = GeoTIFFReader().read(mass_a, Path(mass_a.uri.removeprefix("file://")))
    assert float(np.nansum(mass_dec.arrays["mass"])) == pytest.approx(16.0, rel=1e-5)
    qa_a = next(a for a in res.dataset.assets if a.asset_id.endswith("_QC"))
    qa_dec = GeoTIFFReader().read(qa_a, Path(qa_a.uri.removeprefix("file://")))
    assert set(np.unique(qa_dec.arrays["QC"]).tolist()).issubset({0, 1, 8, 255})


def test_transformations_package_has_no_provider_conditionals() -> None:
    pkg = (
        Path(__file__).resolve().parents[2] / "src" / "geospatial_harmonization" / "transformations"
    )
    for py_file in pkg.glob("*.py"):
        text = py_file.read_text(encoding="utf-8").lower()
        assert not any(
            tok in text for tok in ("modis", "imerg", "gpm", "smap", "nasa_power", "power.larc")
        )
