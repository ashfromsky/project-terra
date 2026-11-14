"""Unit tests for harmonization plan, resampling policy, transform, and job contracts."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from geospatial_harmonization import domain


def _sample_dataset() -> domain.SpatialDataset:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ndvi = domain.VariableSpec("NDVI", "1", "float32", ("y", "x"), "continuous_intensive")
    qa = domain.VariableSpec("QA", "bitmask", "uint8", ("y", "x"), "qa_flag")
    asset = domain.AssetReference("a1", "local://raw/modis.hdf", "hdf4", "application/x-hdf")
    return domain.SpatialDataset(
        dataset_id=uuid4(),
        source_id="mod13q1",
        provider="modis",
        product="MOD13Q1.061",
        variables={"NDVI": ndvi, "QA": qa},
        units={"NDVI": "1", "QA": "bitmask"},
        spatial_metadata=domain.SpatialMetadata("raster", "EPSG:4326"),
        temporal_metadata=domain.TemporalSpec(
            now, now + timedelta(days=16), "16d", "composite", composite_days=16
        ),
        quality_metadata=domain.QualityMetadata("pixel_reliability == 0"),
        assets=(asset,),
        provenance=domain.ProvenanceRecord("modis", "MOD13Q1", "061", now, "0.1.0"),
    )


def test_resampling_policy_blocks_qa_and_extensive_corruption() -> None:
    policy = domain.ResamplingPolicy()
    assert policy.select_for("continuous_intensive") == "bilinear"
    assert policy.select_for("continuous_extensive") == "sum"
    assert policy.select_for("qa_flag") == "nearest"
    assert policy.select_for("categorical", override="mode") == "mode"

    with pytest.raises(domain.QualityPolicyViolationError, match="qa_flag"):
        domain.ResamplingPolicy(qa_method="bilinear")
    with pytest.raises(domain.QualityPolicyViolationError, match="continuous_extensive"):
        policy.select_for("continuous_extensive", override="cubic")


def test_transform_request_validates_grid_budget_and_overrides() -> None:
    ds = _sample_dataset()
    grid = domain.GridSpec(
        "EPSG:4326", 0.25, 0.25, "degree", domain.SpatialBounds(0.0, 0.0, 1.0, 1.0)
    )
    req = domain.TargetGridTransformRequest(ds, grid, ("NDVI", "QA"), max_grid_pixels=16)
    assert req.target_grid.resolved().pixel_count == 16

    with pytest.raises(domain.InvalidGridSpecError, match="max_grid_pixels"):
        domain.TargetGridTransformRequest(ds, grid, max_grid_pixels=8)
    with pytest.raises(domain.IncompatibleDatasetError, match="subset"):
        domain.TargetGridTransformRequest(ds, grid, variables=("UNKNOWN",))
    with pytest.raises(domain.QualityPolicyViolationError, match="qa_flag"):
        domain.TargetGridTransformRequest(ds, grid, resampling_overrides={"QA": "bilinear"})
    with pytest.raises(domain.InvalidGridSpecError, match="resolved GridSpec"):
        domain.TargetGridTransformResult(
            ds, grid, {"NDVI": "bilinear"}, domain.QualityReport(True, 1.0, 0.0)
        )


def test_harmonization_job_and_domain_layer_isolation() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    plan = domain.HarmonizationPlan(uuid4(), "modis", "MOD13Q1.061", {"product": "MOD13Q1.061"})
    job = domain.HarmonizationJob(uuid4(), plan, "pending", now, now)
    assert job.status == "pending"

    with pytest.raises(domain.InvalidTemporalSpecError, match="updated_at"):
        domain.HarmonizationJob(uuid4(), plan, "pending", now, now - timedelta(seconds=1))
    with pytest.raises(domain.InvalidTemporalSpecError, match="timezone-aware"):
        domain.ProcessingResult(
            job.job_id,
            _sample_dataset(),
            domain.QualityReport(True, 1.0, 0.0),
            datetime(2026, 1, 1),
        )

    forbidden = {"fastapi", "sqlalchemy", "rasterio", "boto3", "httpx"}
    domain_root = Path(domain.__file__).parent
    for py_file in domain_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not forbidden.intersection(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
