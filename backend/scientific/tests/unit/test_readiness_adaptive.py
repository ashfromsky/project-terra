"""TDD tests for adaptive data readiness evaluation and resilient assessment execution."""

from datetime import UTC, datetime, timedelta

import numpy as np

from terra_scientific.domain.enums import (
    AggregationOperator,
    AssessmentStatus,
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    SeasonalGrouping,
    TemporalCadence,
    TemporalSemantics,
    VariableSemanticKind,
)
from terra_scientific.domain.models.dataset import (
    ObservationSeries,
    ScientificDataset,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.request import AssessmentRequest, BaselineConfig, TrendConfig
from terra_scientific.domain.models.temporal import TemporalMetadata
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.readiness import (
    READINESS_SPEC_VERSION,
    evaluate_assessment_readiness,
    resolve_aggregation_min_coverage,
    resolve_qa_sufficiency_threshold,
)
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def _power_dataset(
    *,
    years: int,
    dataset_id: str = "power-ds",
    daily_gap_fraction: float = 0.0,
) -> ScientificDataset:
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    total_days = 365 * years
    timestamps = [t0 + timedelta(days=i) for i in range(total_days)]
    t2m_vals: list[float | None] = []
    prec_vals: list[float | None] = []
    for i in range(total_days):
        if daily_gap_fraction > 0 and (i % max(1, round(1.0 / daily_gap_fraction))) == 0:
            t2m_vals.append(-999.0)
            prec_vals.append(-999.0)
        else:
            t2m_vals.append(12.0 + 10.0 * float(np.sin(2.0 * np.pi * (i % 365) / 365.0)))
            prec_vals.append(2.5 + 1.5 * float(np.cos(2.0 * np.pi * (i % 365) / 365.0)))

    t2m_meta = VariableMetadata(
        name="T2M",
        canonical_name="air_temperature_2m",
        units="degC",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        fill_values=(-999.0,),
        valid_range=(-80.0, 60.0),
    )
    prec_meta = VariableMetadata(
        name="PRECTOTCORR",
        canonical_name="bias_corrected_precipitation",
        units="mm/day",
        semantic_kind=VariableSemanticKind.CONTINUOUS_EXTENSIVE,
        fill_values=(-999.0,),
        valid_range=(0.0, 1000.0),
    )
    return ScientificDataset(
        dataset_id=dataset_id,
        source_id=DataSourceId.NASA_POWER,
        product="POWER_DAILY",
        product_version="v10",
        provider="nasa_power",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=55000.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.DAILY,
            semantics=TemporalSemantics.INTERVAL,
            start=timestamps[0],
            end=timestamps[-1] + timedelta(days=1),
        ),
        variables={"T2M": t2m_meta, "PRECTOTCORR": prec_meta},
        series={
            "T2M": ObservationSeries(timestamps=timestamps, values=t2m_vals, metadata=t2m_meta),
            "PRECTOTCORR": ObservationSeries(
                timestamps=timestamps, values=prec_vals, metadata=prec_meta
            ),
        },
    )


def _mod13_cloudy_monthly_pairs(months: int = 12) -> ScientificDataset:
    timestamps: list[datetime] = []
    values: list[float | None] = []
    qa_rel: list[int | None] = []
    base_dt = datetime(2023, 1, 1, tzinfo=UTC)
    for m in range(months):
        yr = 2023 + (m // 12)
        mo = (m % 12) + 1
        d1 = datetime(yr, mo, 1, tzinfo=UTC)
        d2 = datetime(yr, mo, 17, tzinfo=UTC)
        timestamps.extend([d1, d2])
        # Second composite in every month is cloudy (50% sub-step cloud loss per month)
        values.extend([0.52 + 0.01 * m, 0.20])
        qa_rel.extend([0, 3])
    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        is_scaled=True,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
    )
    return ScientificDataset(
        dataset_id="mod13-cloudy",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(
            crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0, is_projected=True
        ),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.SIXTEEN_DAY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=16,
            start=base_dt,
            end=timestamps[-1] + timedelta(days=16),
        ),
        variables={"NDVI": meta},
        series={
            "NDVI": ObservationSeries(
                timestamps=timestamps,
                values=values,
                qa_layers={"pixel_reliability": qa_rel},
                metadata=meta,
            )
        },
    )


def test_adaptive_thresholds_differ_by_source_and_qa_level() -> None:
    modis_std, modis_rat = resolve_qa_sufficiency_threshold(
        DataSourceId.MODIS_MOD13Q1, "MOD13Q1.061", QaPolicyLevel.STANDARD
    )
    power_std, power_rat = resolve_qa_sufficiency_threshold(
        DataSourceId.NASA_POWER, "POWER_DAILY", QaPolicyLevel.STANDARD
    )
    smap_perm, _ = resolve_qa_sufficiency_threshold(
        DataSourceId.SMAP_SPL3SMP_E, "SPL3SMP_E.006", QaPolicyLevel.PERMISSIVE
    )
    assert power_std > modis_std
    assert smap_perm < modis_std
    assert "MOD13Q1" in modis_rat or "optical" in modis_rat.lower()
    assert "MERRA-2" in power_rat or "POWER" in power_rat

    modis_agg, _ = resolve_aggregation_min_coverage(
        DataSourceId.MODIS_MOD13Q1,
        TemporalCadence.SIXTEEN_DAY,
        TemporalCadence.MONTHLY,
        QaPolicyLevel.STANDARD,
    )
    power_agg, _ = resolve_aggregation_min_coverage(
        DataSourceId.NASA_POWER,
        TemporalCadence.DAILY,
        TemporalCadence.MONTHLY,
        QaPolicyLevel.STANDARD,
    )
    assert modis_agg <= 0.5
    assert power_agg >= 0.7


def test_pre_run_readiness_diagnostics_explain_gaps_and_available_metrics() -> None:
    ds_1yr = _power_dataset(years=1)
    req_1yr = AssessmentRequest(
        request_id="readiness-1yr",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2021, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        qa_level=QaPolicyLevel.STANDARD,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FULL_PERIOD_EXPLICIT,
            allow_explicit_full_period=True,
            seasonal_grouping=SeasonalGrouping.CALENDAR_MONTH,
        ),
    )

    report = evaluate_assessment_readiness(req_1yr, datasets=[ds_1yr])
    assert report.spec_version == READINESS_SPEC_VERSION
    assert report.overall_status == "partial"
    assert len(report.datasets) == 1
    assert report.datasets[0].source_id == DataSourceId.NASA_POWER

    by_id = {m.metric_id: m for m in report.metrics}
    assert by_id["trend_mann_kendall"].status == "available"
    assert by_id["baseline_climatology"].status in {"degraded", "unavailable"}
    assert by_id["cross_variable_association"].status == "available"
    assert any(
        c.status == "failed" and c.category == "baseline" and c.remediation for c in report.criteria
    )
    assert any(c.status == "passed" and c.category == "trend" for c in report.criteria)
    assert report.suggested_window_start is not None
    assert report.suggested_window_start < req_1yr.analysis_start


def test_pipeline_computes_available_trends_and_surfaces_detailed_readiness() -> None:
    ds_1yr = _power_dataset(years=1)
    req = AssessmentRequest(
        request_id="partial-1yr-run",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2021, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FULL_PERIOD_EXPLICIT,
            allow_explicit_full_period=True,
            seasonal_grouping=SeasonalGrouping.CALENDAR_MONTH,
            min_years_required=3,
            min_samples_per_bin=3,
        ),
    )
    res = ScientificAssessmentService().run_assessment(req, datasets=[ds_1yr])
    assert res.status == AssessmentStatus.COMPLETED_PARTIAL
    assert len(res.trends) == 2
    assert res.cross_variable is not None
    assert res.readiness is not None
    assert res.readiness.overall_status == "partial"
    assert len(res.readiness.criteria) >= 4
    assert any(c.status == "failed" and "3" in c.required_summary for c in res.readiness.criteria)


def test_mod13_cloudy_composites_aggregate_monthly_under_adaptive_coverage() -> None:
    # 50% QA-valid optical composites (1 of 2 per month) previously failed hardcoded 0.7 threshold.
    ds = _mod13_cloudy_monthly_pairs(months=12)
    req = AssessmentRequest(
        request_id="mod13-cloudy-12m",
        analysis_start=datetime(2023, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2023, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        qa_level=QaPolicyLevel.PERMISSIVE,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FULL_PERIOD_EXPLICIT,
            allow_explicit_full_period=True,
            min_years_required=3,
            min_samples_per_bin=3,
        ),
        trend=TrendConfig(min_samples=6),
    )
    res = ScientificAssessmentService().run_assessment(req, datasets=[ds])
    assert res.status == AssessmentStatus.COMPLETED_PARTIAL
    assert len(res.temporal_series) == 1
    assert sum(1 for v in res.temporal_series[0].values if v is not None) == 12
    assert len(res.trends) == 1
    assert res.trends[0].valid_count == 12


def test_power_precip_sum_converts_daily_rate_units_to_mm() -> None:
    ds = _power_dataset(years=1)
    req = AssessmentRequest(
        request_id="power-sum-check",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2021, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        aggregation_operator=AggregationOperator.SUM,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FULL_PERIOD_EXPLICIT,
            allow_explicit_full_period=True,
        ),
    )
    res = ScientificAssessmentService().run_assessment(req, datasets=[ds])
    # Mixed dataset: PRECTOTCORR summed cleanly to mm, T2M averaged safely without crashing
    by_var = {ts.variable_name: ts for ts in res.temporal_series}
    assert by_var["PRECTOTCORR"].units == "mm"
    assert by_var["T2M"].units == "degC"
    assert by_var["T2M"].aggregation_operator == AggregationOperator.MEAN
    assert by_var["PRECTOTCORR"].aggregation_operator == AggregationOperator.SUM
    t2m_vals = [v for v in by_var["T2M"].values if v is not None]
    assert max(t2m_vals) < 35.0


def test_insufficient_data_still_populates_full_readiness_diagnostics() -> None:
    ds_short = _power_dataset(years=1)
    short_t2m = ds_short.series["T2M"]
    tiny_ds = ds_short.model_copy(
        update={
            "variables": {"T2M": ds_short.variables["T2M"]},
            "series": {
                "T2M": short_t2m.model_copy(
                    update={
                        "timestamps": short_t2m.timestamps[:2],
                        "values": [-999.0, -999.0],
                    }
                )
            },
        }
    )
    req = AssessmentRequest(
        request_id="all-missing",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2021, 1, 3, tzinfo=UTC),
        target_cadence=TemporalCadence.DAILY,
    )
    res = ScientificAssessmentService().run_assessment(req, datasets=[tiny_ds])
    assert res.status == AssessmentStatus.INSUFFICIENT_DATA
    assert res.readiness is not None
    assert res.readiness.overall_status == "insufficient"
    assert any(c.status == "failed" for c in res.readiness.criteria)
    assert len(res.readiness.recommended_actions) >= 1
