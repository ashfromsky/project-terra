"""Tests for API request/response schema validation and domain mapping."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geospatial_harmonization.api.schemas import HarmonizeRequest, JobOut
from geospatial_harmonization.domain.exceptions import InvalidGridSpecError
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob


def test_harmonize_request_maps_to_domain_plan_and_validates_grid() -> None:
    req = HarmonizeRequest.model_validate(
        {
            "provider": "generic",
            "product": "ndvi",
            "request_payload": {"url": "https://data.example.org/ndvi.tif"},
            "target_grid": {
                "crs": "EPSG:4326",
                "resolution_x": 0.5,
                "resolution_y": 0.5,
                "resolution_unit": "degree",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 2.0, "max_y": 2.0},
            },
            "target_temporal": {
                "start": "2026-07-01T00:00:00Z",
                "end": "2026-07-02T00:00:00Z",
                "cadence": "daily",
                "semantics": "interval",
            },
            "variables": ["band_1"],
        }
    )
    plan = req.to_plan()
    assert plan.target_grid is not None
    assert plan.target_grid.resolved().width == 4
    assert plan.variables == ("band_1",)

    now = datetime(2026, 7, 1, tzinfo=UTC)
    job = HarmonizationJob(uuid4(), plan, "pending", now, now)
    out = JobOut.from_domain(job)
    assert out.provider == "generic" and out.status == "pending"

    bad = HarmonizeRequest.model_validate(
        {
            "provider": "generic",
            "product": "ndvi",
            "target_grid": {
                "crs": "EPSG:4326",
                "resolution_x": 0.3,
                "resolution_y": 0.3,
                "resolution_unit": "degree",
                "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
            },
        }
    )
    with pytest.raises(InvalidGridSpecError):
        bad.to_plan()


def test_asset_and_dataset_out_redact_internal_paths_and_discover_validation() -> None:
    from datetime import timedelta

    from pydantic import ValidationError

    from geospatial_harmonization.api.schemas import (
        AssetOut,
        DatasetOut,
        DatasetProvenanceOut,
        DiscoverRequest,
    )
    from geospatial_harmonization.domain.models.dataset import (
        AssetReference,
        ProvenanceRecord,
        QualityMetadata,
        SpatialDataset,
        SpatialMetadata,
        VariableSpec,
    )
    from geospatial_harmonization.domain.models.grid import SpatialBounds
    from geospatial_harmonization.domain.models.temporal import TemporalSpec

    local_asset = AssetReference(
        asset_id="raw/modis/a.hdf",
        uri="file:///var/data/secret/raw/modis/a.hdf",
        data_format="hdf4",
        media_type="application/x-hdf",
        checksum_sha256="abc123",
        size_bytes=512,
        storage_key="raw/modis/a.hdf",
        zone="raw",
    )
    s3_asset = AssetReference(
        asset_id="derived/modis/b.tif",
        uri="s3://private-bucket/ghs/derived/modis/b.tif",
        data_format="geotiff",
        media_type="image/tiff",
        storage_key="derived/modis/b.tif",
        zone="derived",
    )
    assert AssetOut.from_domain(local_asset).uri is None
    assert AssetOut.from_domain(local_asset).storage_key == "raw/modis/a.hdf"
    assert AssetOut.from_domain(s3_asset).uri is None
    assert AssetOut.from_domain(s3_asset).zone == "derived"

    t0 = datetime(2026, 7, 1, tzinfo=UTC)
    ds = SpatialDataset(
        dataset_id=uuid4(),
        source_id="MOD13Q1.A2026182",
        provider="modis",
        product="MOD13Q1.061",
        product_version="061",
        granule_id="MOD13Q1.A2026182",
        variables={
            "NDVI": VariableSpec("NDVI", "1", "float32", ("y", "x"), "continuous_intensive")
        },
        units={"NDVI": "1"},
        spatial_metadata=SpatialMetadata("raster", "EPSG:4326", SpatialBounds(0.0, 0.0, 1.0, 1.0)),
        temporal_metadata=TemporalSpec(
            t0, t0 + timedelta(days=16), "16d", "composite", composite_days=16
        ),
        quality_metadata=QualityMetadata("strict", 1.0),
        assets=(local_asset,),
        provenance=ProvenanceRecord(
            provider="modis",
            product="MOD13Q1.061",
            product_version="061",
            retrieved_at=t0,
            software_version="0.1.0",
            source_urls=(
                "file:///var/data/secret/a.hdf",
                "https://lpdaac.earthdata.nasa.gov/a.hdf",
            ),
        ),
    )
    out = DatasetOut.from_domain(ds)
    prov_out = DatasetProvenanceOut.from_domain(ds)
    assert "/var/data/secret" not in out.model_dump_json()
    assert "/var/data/secret" not in prov_out.model_dump_json()
    assert out.granule_id == "MOD13Q1.A2026182"
    assert out.assets[0].uri is None
    assert prov_out.provenance["source_urls"] == [
        "local://a.hdf",
        "https://lpdaac.earthdata.nasa.gov/a.hdf",
    ]

    with pytest.raises(ValidationError):
        DiscoverRequest.model_validate(
            {
                "provider": "modis",
                "product": "MOD13Q1.061",
                "bbox": [31.0, 50.0, 30.0, 51.0],
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-02T00:00:00Z",
            }
        )
    with pytest.raises(ValidationError):
        DiscoverRequest.model_validate(
            {
                "provider": "modis",
                "product": "MOD13Q1.061",
                "bbox": [30.0, 50.0, 31.0, 51.0],
                "start_time": "2026-07-03T00:00:00Z",
                "end_time": "2026-07-02T00:00:00Z",
            }
        )
