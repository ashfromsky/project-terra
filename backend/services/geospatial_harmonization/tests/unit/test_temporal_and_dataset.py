"""Unit tests for TemporalSpec, DecodedDataset, and SpatialDataset domain contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from geospatial_harmonization import domain


def _sample_var() -> domain.VariableSpec:
    return domain.VariableSpec(
        name="T2M",
        units="degC",
        dtype="float32",
        dimensions=("time", "lat", "lon"),
        semantics="continuous_intensive",
        nodata=-999.0,
    )


def test_temporal_spec_enforces_timezone_and_composite_semantics() -> None:
    start, end = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 17, tzinfo=UTC)
    comp = domain.TemporalSpec(
        start, end, "16d", "composite", aggregation="quality_weighted_mean", composite_days=16
    )
    assert comp.duration_seconds == 16 * 86400
    assert domain.TemporalSpec(start, start, "instant", "instantaneous").duration_seconds == 0.0

    with pytest.raises(domain.InvalidTemporalSpecError, match="timezone-aware"):
        domain.TemporalSpec(datetime(2026, 1, 1), end, "16d", "interval")
    with pytest.raises(domain.InvalidTemporalSpecError, match="composite_days"):
        domain.TemporalSpec(start, end, "16d", "composite")
    with pytest.raises(domain.InvalidTemporalSpecError, match="start == end"):
        domain.TemporalSpec(start, end, "1d", "instantaneous")


def test_variable_and_quality_guards() -> None:
    with pytest.raises(domain.QualityPolicyViolationError, match="scale_factor"):
        domain.VariableSpec("QC_Day", "bitmask", "uint8", ("y", "x"), "qa_flag", scale_factor=0.02)
    with pytest.raises(domain.IncompatibleDatasetError, match="valid_range"):
        domain.VariableSpec(
            "NDVI", "1", "float32", ("y", "x"), "continuous_intensive", valid_range=(1.0, 0.0)
        )
    with pytest.raises(domain.QualityPolicyViolationError, match="excluded_count"):
        domain.QualityMetadata(qa_policy="qc", excluded_count=-1)


def test_spatial_dataset_preserves_canonical_envelope_and_validates_units() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    var = _sample_var()
    asset = domain.AssetReference("power-1", "local://raw/t2m.json", "json", "application/json")
    decoded = domain.DecodedDataset(
        asset, "json", {"T2M": var}, {"time": 1, "lat": 1, "lon": 1}, crs="EPSG:4326"
    )
    assert decoded.crs == "EPSG:4326"

    spatial = domain.SpatialMetadata(
        "point", "EPSG:4326", domain.SpatialBounds(-1.0, 50.0, 1.0, 52.0), point_count=1
    )
    temporal = domain.TemporalSpec(now, datetime(2026, 1, 2, tzinfo=UTC), "1d", "interval")
    quality = domain.QualityMetadata("fill == -999", valid_observation_fraction=1.0)
    provenance = domain.ProvenanceRecord("nasa_power", "MERRA-2", "v1", now, "0.1.0")

    envelope = domain.SpatialDataset(
        dataset_id=uuid4(),
        source_id="nasa-power-point",
        provider="nasa_power",
        product="POWER_DAILY",
        variables={"T2M": var},
        units={"T2M": "degC"},
        spatial_metadata=spatial,
        temporal_metadata=temporal,
        quality_metadata=quality,
        assets=(asset,),
        provenance=provenance,
        extensions={"nasa_power": {"community": "RE"}},
    )
    assert envelope.extensions["nasa_power"] == {"community": "RE"}

    with pytest.raises(domain.IncompatibleDatasetError, match="Unit mismatch"):
        domain.SpatialDataset(
            uuid4(),
            "nasa-power-point",
            "nasa_power",
            "POWER_DAILY",
            {"T2M": var},
            {"T2M": "K"},
            spatial,
            temporal,
            quality,
            (asset,),
            provenance,
        )
