"""Unit tests for Scientific Core domain contracts and models."""

from datetime import UTC, datetime
from math import isnan

import pytest

from terra_scientific.domain.enums import (
    AssessmentStatus,
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    TemporalCadence,
    TemporalSemantics,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.dataset import (
    ObservationSeries,
    ScientificDataset,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.request import (
    AssessmentRequest,
    BaselineConfig,
)
from terra_scientific.domain.models.result import ScientificAssessmentResult
from terra_scientific.domain.models.temporal import TemporalMetadata


def test_observation_series_normalizes_utc_and_rejects_mismatched_lengths() -> None:
    t0 = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        is_scaled=True,
        valid_range=(-0.2, 1.0),
    )
    series = ObservationSeries(
        timestamps=[t0],
        values=[0.55],
        qa_layers={"pixel_reliability": [0]},
        metadata=meta,
    )
    ts, vals, qa = series.to_numpy()
    assert len(ts) == 1
    assert ts[0].tzinfo == UTC
    assert vals[0] == pytest.approx(0.55)
    assert qa["pixel_reliability"][0] == 0

    with pytest.raises(ValueError, match="timestamps and values"):
        ObservationSeries(
            timestamps=[t0, datetime(2020, 1, 17, 12, 0, tzinfo=UTC)],
            values=[0.55],
            metadata=meta,
        )


def test_observation_series_requires_timezone_aware_timestamps() -> None:
    meta = VariableMetadata(
        name="T2M",
        canonical_name="air_temperature_2m",
        units="degC",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ObservationSeries(
            timestamps=[datetime(2020, 1, 1, 0, 0)],
            values=[15.2],
            metadata=meta,
        )


def test_observation_series_preserves_none_as_nan_never_zero() -> None:
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    t1 = datetime(2020, 1, 2, tzinfo=UTC)
    meta = VariableMetadata(
        name="precipitation",
        canonical_name="precipitation_rate",
        units="mm/hr",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    series = ObservationSeries(timestamps=[t0, t1], values=[2.5, None], metadata=meta)
    _, vals, _ = series.to_numpy()
    assert vals[0] == pytest.approx(2.5)
    assert isnan(float(vals[1]))


def test_scientific_dataset_rejects_gibs_quantitative_usage() -> None:
    with pytest.raises(ScientificInputError, match="GIBS"):
        ScientificDataset(
            dataset_id="gibs-1",
            source_id=DataSourceId.NASA_GIBS,
            product="MODIS_Terra_CorrectedReflectance_TrueColor",
            product_version="1",
            provider="nasa_gibs",
            spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=250.0),
            temporal_metadata=TemporalMetadata(
                cadence=TemporalCadence.DAILY,
                semantics=TemporalSemantics.INSTANTANEOUS,
                start=datetime(2020, 1, 1, tzinfo=UTC),
                end=datetime(2020, 1, 2, tzinfo=UTC),
            ),
            variables={},
        )


def test_assessment_request_and_result_json_roundtrip() -> None:
    req = AssessmentRequest(
        request_id="req-001",
        region_id="reg-123",
        region_name="Polissia AOI",
        region_area_km2=450.5,
        analysis_start=datetime(2015, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 12, 31, tzinfo=UTC),
        qa_level=QaPolicyLevel.STRICT,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2015, 1, 1, tzinfo=UTC),
            end=datetime(2019, 12, 31, tzinfo=UTC),
        ),
    )
    assert req.qa_level == QaPolicyLevel.STRICT

    result = ScientificAssessmentResult(
        assessment_id="assess-001",
        request=req,
        status=AssessmentStatus.INSUFFICIENT_DATA,
        summary_warnings=["No datasets supplied"],
    )
    payload = result.model_dump_json()
    restored = ScientificAssessmentResult.model_validate_json(payload)
    assert restored.assessment_id == "assess-001"
    assert restored.status == AssessmentStatus.INSUFFICIENT_DATA
    assert restored.request.baseline.baseline_type == BaselineType.FIXED_REFERENCE
