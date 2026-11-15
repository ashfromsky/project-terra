"""End-to-end integration tests for ScientificAssessmentService full pipeline."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

from terra_scientific.domain.enums import (
    AssessmentStatus,
    BaselineType,
    DataSourceId,
    QaPolicyLevel,
    SeasonalGrouping,
    StageStatus,
    TemporalCadence,
    TemporalSemantics,
    VariableSemanticKind,
)
from terra_scientific.domain.models.dataset import (
    ObservationSeries,
    ScientificDataset,
    ScientificGridStack,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.request import (
    AssessmentRequest,
    BaselineConfig,
    SpatialConfig,
    TrendConfig,
)
from terra_scientific.domain.models.temporal import TemporalMetadata
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def _build_multi_year_inputs() -> tuple[list[ScientificDataset], dict[str, ScientificGridStack]]:
    rng = np.random.default_rng(1234)
    # 7-year monthly series (2018-2024) with mid-2022 vegetation anomaly dip.
    timestamps: list[datetime] = []
    ndvi_vals: list[float | None] = []
    ndvi_qa: list[int | None] = []
    imerg_ts: list[datetime] = []
    imerg_rates: list[float | None] = []
    t2m_vals: list[float | None] = []

    for year in range(2018, 2025):
        for month in range(1, 13):
            ts = datetime(year, month, 1, tzinfo=UTC)
            timestamps.append(ts)
            season = 0.18 * float(np.sin(2.0 * np.pi * (month - 1) / 12.0))
            trend = 0.008 * (year - 2018)
            val = 0.55 + season + trend + float(rng.normal(0.0, 0.015))
            if year == 2022 and month in {6, 7, 8}:
                val -= 0.22
            elif year == 2022 and month in {9, 10, 11}:
                val -= 0.08 * (12 - month) / 3.0
            ndvi_vals.append(round(val, 4))
            ndvi_qa.append(0)

            t2m_vals.append(round(12.0 + 10.0 * float(np.sin(2.0 * np.pi * (month - 4) / 12.0)), 2))

            # Two 30-min samples inside day 1 representing monthly rate sample
            rate_base = 3.0 + 1.5 * float(np.cos(2.0 * np.pi * (month - 1) / 12.0))
            if year == 2022 and month in {5, 6, 7}:
                rate_base = 0.2
            imerg_ts.append(ts)
            imerg_ts.append(ts + timedelta(minutes=30))
            imerg_rates.extend([rate_base, rate_base])

    ndvi_meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        is_scaled=True,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
    )
    ndvi_ds = ScientificDataset(
        dataset_id="mod13-poly",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(
            crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0, is_projected=True
        ),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=16,
            start=timestamps[0],
            end=timestamps[-1],
        ),
        variables={"NDVI": ndvi_meta},
        series={
            "NDVI": ObservationSeries(
                timestamps=timestamps,
                values=ndvi_vals,
                qa_layers={"pixel_reliability": ndvi_qa},
                metadata=ndvi_meta,
            )
        },
    )

    precip_meta = VariableMetadata(
        name="Grid/precipitation",
        canonical_name="precipitation_rate",
        units="mm/hr",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        fill_values=(-9999.9,),
        valid_range=(0.0, 400.0),
    )
    precip_ds = ScientificDataset(
        dataset_id="imerg-poly",
        source_id=DataSourceId.GPM_IMERG,
        product="GPM_3IMERGHH.07",
        product_version="07",
        provider="nasa_earthdata",
        run_type="Final",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=11132.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.HALF_HOURLY,
            semantics=TemporalSemantics.INTERVAL,
            start=imerg_ts[0],
            end=imerg_ts[-1],
        ),
        variables={"Grid/precipitation": precip_meta},
        series={
            "Grid/precipitation": ObservationSeries(
                timestamps=imerg_ts,
                values=imerg_rates,
                metadata=precip_meta,
            )
        },
    )

    t2m_meta = VariableMetadata(
        name="T2M",
        canonical_name="air_temperature_2m",
        units="degC",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        fill_values=(-999.0,),
        valid_range=(-80.0, 60.0),
        attributes={"origin_dataset": "MERRA-2"},
    )
    power_ds = ScientificDataset(
        dataset_id="power-poly",
        source_id=DataSourceId.NASA_POWER,
        product="POWER_DAILY",
        product_version="v10",
        provider="nasa_power",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=55000.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.INTERVAL,
            start=timestamps[0],
            end=timestamps[-1],
        ),
        variables={"T2M": t2m_meta},
        series={
            "T2M": ObservationSeries(
                timestamps=timestamps,
                values=t2m_vals,
                metadata=t2m_meta,
            )
        },
    )

    # 3D grid stack for spatial stage [T, 5, 5]
    grid_vals = np.broadcast_to(
        np.array(ndvi_vals, dtype=np.float64)[:, None, None], (len(timestamps), 5, 5)
    ).copy()
    grid_vals[:, :2, :2] += 0.05
    grid_stack = ScientificGridStack(
        dataset_id="mod13-poly",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        variable=ndvi_meta,
        spatial_support=SpatialSupport(
            crs=MODIS_SINUSOIDAL_WKT,
            nominal_resolution_m=250.0,
            grid_shape=(5, 5),
            is_projected=True,
        ),
        timestamps=timestamps,
        data=grid_vals,
    )

    return [ndvi_ds, precip_ds, power_ds], {"mod13-poly:NDVI": grid_stack}


def test_full_end_to_end_pipeline_produces_traceable_assessment_and_artifacts(
    tmp_path: Path,
) -> None:
    datasets, grid_stacks = _build_multi_year_inputs()
    request = AssessmentRequest(
        request_id="req-full-001",
        region_id="reg-polissia",
        region_name="Polissia AOI",
        region_area_km2=320.0,
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        qa_level=QaPolicyLevel.STANDARD,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
            seasonal_grouping=SeasonalGrouping.CALENDAR_MONTH,
            min_years_required=3,
            min_samples_per_bin=3,
        ),
        trend=TrendConfig(min_samples=6),
        spatial=SpatialConfig(permutations=19),
        output_artifact_dir=str(tmp_path),
    )

    service = ScientificAssessmentService()
    result = service.run_assessment(request, datasets=datasets, grid_stacks=grid_stacks)

    assert result.status == AssessmentStatus.COMPLETED
    assert len(result.quality_reports) == 3
    assert len(result.temporal_series) == 3
    assert len(result.baselines) == 3
    assert len(result.anomalies) == 3
    assert len(result.trends) == 3
    assert len(result.seasonal_trends) == 3
    assert len(result.spatial_stats) == 1
    assert result.spatial_stats[0].valid_pixel_count == 25
    assert result.cross_variable is not None
    assert len(result.cross_variable.pairwise) >= 2
    assert len(result.disturbances) >= 1
    assert len(result.resilience) >= 1
    assert result.resilience[0].composite_tri.status == "unavailable_unvalidated"
    assert result.resilience[0].composite_tri.value is None
    assert result.uncertainty is not None
    assert result.provenance is not None
    assert len(result.provenance.dataset_lineage) == 3
    assert len(result.provenance.methods_invoked) >= 5
    assert result.provenance.input_digest_sha256
    assert "assessment_result_json" in result.artifact_manifest
    assert Path(result.artifact_manifest["assessment_result_json"]).exists()


def test_pipeline_supports_partial_dataset_availability_without_crashing() -> None:
    datasets, _ = _build_multi_year_inputs()
    ndvi_only = datasets[0]
    # Add an empty/insufficient custom dataset
    bad_meta = VariableMetadata(
        name="broken",
        canonical_name="broken",
        units="u",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    bad_ds = ScientificDataset(
        dataset_id="empty-ds",
        source_id=DataSourceId.CUSTOM,
        product="custom",
        product_version="1",
        provider="custom",
        spatial_support=SpatialSupport(crs="EPSG:4326"),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.INTERVAL,
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2020, 2, 1, tzinfo=UTC),
        ),
        variables={"broken": bad_meta},
        series={
            "broken": ObservationSeries(
                timestamps=[datetime(2020, 1, 1, tzinfo=UTC)],
                values=[None],
                metadata=bad_meta,
            )
        },
    )

    request = AssessmentRequest(
        request_id="req-partial",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 12, 31, tzinfo=UTC),
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
            min_years_required=3,
            min_samples_per_bin=3,
        ),
        allow_partial_datasets=True,
    )
    res = ScientificAssessmentService().run_assessment(request, datasets=[ndvi_only, bad_ds])
    assert res.status == AssessmentStatus.COMPLETED_PARTIAL
    assert any(st.status == StageStatus.PARTIAL for st in res.stages)
    assert len(res.trends) >= 1


def test_pipeline_resilience_dimensions_ols_stability_and_bounded_recovery() -> None:
    rng = np.random.default_rng(42)
    timestamps: list[datetime] = []
    ndvi_vals: list[float | None] = []
    precip_vals: list[float | None] = []

    for year in range(2018, 2025):
        for month in range(1, 13):
            ts = datetime(year, month, 1, tzinfo=UTC)
            timestamps.append(ts)
            season = 0.15 * float(np.sin(2.0 * np.pi * (month - 1) / 12.0))
            precip = (
                80.0
                + 25.0 * float(np.cos(2.0 * np.pi * (month - 1) / 12.0))
                + float(rng.normal(0.0, 5.0))
            )
            # Two distinct drought shocks separated cleanly in 2022 and 2023.
            shock = 0.0
            if year == 2022 and month in {4, 5, 6}:
                shock = -0.25 if month == 5 else -0.18
            elif year == 2023 and month in {2, 3, 4}:
                shock = -0.35 if month == 3 else -0.22
            val = 0.55 + season + 0.002 * (precip - 80.0) + float(rng.normal(0.0, 0.012)) + shock
            ndvi_vals.append(val)
            precip_vals.append(precip)

    ndvi_meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        valid_range=(-0.2, 1.0),
    )
    precip_meta = VariableMetadata(
        name="precip",
        canonical_name="precipitation",
        units="mm/month",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    precip_scaled_meta = VariableMetadata(
        name="precip",
        canonical_name="precipitation",
        units="um/month",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )

    ndvi_ds = ScientificDataset(
        dataset_id="mod13-test",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=16,
            start=timestamps[0],
            end=timestamps[-1],
        ),
        variables={"NDVI": ndvi_meta},
        series={
            "NDVI": ObservationSeries(timestamps=timestamps, values=ndvi_vals, metadata=ndvi_meta)
        },
    )
    precip_ds = ScientificDataset(
        dataset_id="gpm-test",
        source_id=DataSourceId.GPM_IMERG,
        product="GPM_3IMERGM.07",
        product_version="07",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=10000.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.INTERVAL,
            start=timestamps[0],
            end=timestamps[-1],
        ),
        variables={"precip": precip_meta},
        series={
            "precip": ObservationSeries(
                timestamps=timestamps, values=precip_vals, metadata=precip_meta
            )
        },
    )
    precip_scaled_ds = ScientificDataset(
        dataset_id="gpm-test-scaled",
        source_id=DataSourceId.GPM_IMERG,
        product="GPM_3IMERGM.07",
        product_version="07",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=10000.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.MONTHLY,
            semantics=TemporalSemantics.INTERVAL,
            start=timestamps[0],
            end=timestamps[-1],
        ),
        variables={"precip": precip_scaled_meta},
        series={
            "precip": ObservationSeries(
                timestamps=timestamps,
                values=[v * 1000.0 if v is not None else None for v in precip_vals],
                metadata=precip_scaled_meta,
            )
        },
    )

    req = AssessmentRequest(
        request_id="req-res-check",
        analysis_start=datetime(2021, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
            min_years_required=3,
            min_samples_per_bin=3,
        ),
    )

    res_mm = ScientificAssessmentService().run_assessment(req, datasets=[ndvi_ds, precip_ds])
    res_um = ScientificAssessmentService().run_assessment(req, datasets=[ndvi_ds, precip_scaled_ds])

    ndvi_res = next(r for r in res_mm.resilience if r.variable_name == "NDVI")
    precip_res_mm = next(r for r in res_mm.resilience if r.variable_name == "precip")
    precip_res_um = next(r for r in res_um.resilience if r.variable_name == "precip")

    # 1. Resistance tracked per negative event without mixing positive shocks.
    ndvi_recoveries = [rec for rec in res_mm.recoveries if rec.variable_name == "NDVI"]
    assert ndvi_res.resistance.available is True
    assert len(ndvi_res.resistance.event_values) >= 2
    assert len(ndvi_res.resistance.event_values) == len(ndvi_recoveries)

    # 2. Recovery events do not overlap into subsequent disturbances.
    for prev_rec, next_rec in pairwise(ndvi_recoveries):
        assert prev_rec.observation_end < next_rec.event_start

    # 3. Stability is invariant when physical units of precipitation scale by 1000x.
    assert precip_res_mm.stability.available is True
    assert precip_res_um.stability.available is True
    stab_mm = precip_res_mm.stability.value or 0.0
    stab_um = precip_res_um.stability.value or 0.0
    assert abs(stab_mm - stab_um) < 1e-9

    # 4. Sensitivity equals OLS slope (not Pearson r) and preserves physical units.
    assert res_mm.cross_variable is not None
    top_pair = res_mm.cross_variable.pairwise[0]
    assert ndvi_res.sensitivity.value == top_pair.ols_slope
    assert abs((ndvi_res.sensitivity.value or 0.0) - (top_pair.pearson_r or 0.0)) > 0.05
    assert ndvi_res.sensitivity.unit == "dimensionless/mm/month"


def test_end_to_end_pipeline_from_mapped_ghs_mod13_imerg_smap_nasa_power_payloads() -> None:
    from terra_scientific.adapters.ghs import map_ghs_dataset_payload

    rng = np.random.default_rng(77)
    timestamps: list[str] = []
    ndvi_vals: list[float] = []
    ndvi_qa: list[int] = []
    precip_vals: list[float] = []
    pqi_vals: list[float] = []
    smap_vals: list[float] = []
    smap_qf: list[int] = []
    smap_sf: list[int] = []
    overpass_tags: list[str] = []
    t2m_vals: list[float] = []

    for year in range(2020, 2025):
        for month in range(1, 13):
            timestamps.append(datetime(year, month, 1, tzinfo=UTC).isoformat())
            season = 0.14 * float(np.sin(2.0 * np.pi * (month - 1) / 12.0))
            ndvi = 0.55 + season + float(rng.normal(0.0, 0.01))
            if year == 2023 and month in {6, 7}:
                ndvi -= 0.16
            ndvi_vals.append(round(ndvi, 4))
            ndvi_qa.append(0)
            precip_vals.append(
                round(45.0 + 15.0 * float(np.cos(2.0 * np.pi * (month - 1) / 12.0)), 2)
            )
            pqi_vals.append(0.9)
            smap_vals.append(
                round(0.26 + 0.04 * float(np.sin(2.0 * np.pi * (month - 1) / 12.0)), 3)
            )
            smap_qf.append(0)
            smap_sf.append(0)
            overpass_tags.append("AM")
            t2m_vals.append(round(14.0 + 8.0 * float(np.sin(2.0 * np.pi * (month - 4) / 12.0)), 2))

    common_temporal = {
        "start": timestamps[0],
        "end": timestamps[-1],
        "cadence": "monthly",
        "semantics": "interval",
    }
    mod13_ds = map_ghs_dataset_payload(
        {
            "dataset_id": "ghs-mod13",
            "source_id": "modis_terra_vegetation",
            "provider": "modis",
            "product": "MOD13Q1.061",
            "product_version": "061",
            "variables": {
                "250m 16 days NDVI": {
                    "name": "250m 16 days NDVI",
                    "units": "dimensionless",
                    "dtype": "float32",
                    "semantics": "continuous_intensive",
                    "nodata": -3000.0,
                }
            },
            "spatial_metadata": {"crs": MODIS_SINUSOIDAL_WKT, "nominal_resolution_m": 250.0},
            "temporal_metadata": {
                **common_temporal,
                "semantics": "composite",
                "composite_days": 16,
            },
            "extensions": {
                "time_series": {
                    "NDVI": {
                        "timestamps": timestamps,
                        "values": ndvi_vals,
                        "is_scaled": True,
                        "qa_layers": {"pixel_reliability": ndvi_qa},
                    }
                }
            },
        }
    )
    imerg_ds = map_ghs_dataset_payload(
        {
            "dataset_id": "ghs-imerg",
            "source_id": "gpm_imerg",
            "provider": "gpm_imerg",
            "product": "GPM_3IMERGHH.07",
            "product_version": "07",
            "variables": {
                "Grid/precipitation": {
                    "name": "Grid/precipitation",
                    "units": "mm",
                    "dtype": "float32",
                    "semantics": "continuous_extensive",
                    "nodata": -9999.9,
                }
            },
            "spatial_metadata": {"crs": "EPSG:4326", "nominal_resolution_m": 11132.0},
            "temporal_metadata": common_temporal,
            "extensions": {
                "run_type": "Final",
                "time_series": {
                    "precipitation": {
                        "timestamps": timestamps,
                        "values": precip_vals,
                        "is_scaled": True,
                        "qa_layers": {"precipitationQualityIndex": pqi_vals},
                    }
                },
            },
        }
    )
    smap_ds = map_ghs_dataset_payload(
        {
            "dataset_id": "ghs-smap",
            "source_id": "smap_spl3smp_e",
            "provider": "smap",
            "product": "SPL3SMP_E.006",
            "product_version": "006",
            "variables": {
                "Soil_Moisture_Retrieval_Data_AM/soil_moisture": {
                    "name": "Soil_Moisture_Retrieval_Data_AM/soil_moisture",
                    "units": "cm^3/cm^3",
                    "dtype": "float32",
                    "semantics": "continuous_intensive",
                    "nodata": -9999.0,
                }
            },
            "spatial_metadata": {
                "crs": "EPSG:6933",
                "nominal_resolution_m": 9000.0,
                "native_footprint_km": 36.0,
            },
            "temporal_metadata": {**common_temporal, "semantics": "composite", "composite_days": 1},
            "extensions": {
                "overpass_mode": "am_only",
                "time_series": {
                    "soil_moisture": {
                        "timestamps": timestamps,
                        "values": smap_vals,
                        "is_scaled": True,
                        "overpass_tags": overpass_tags,
                        "qa_layers": {
                            "retrieval_qual_flag": smap_qf,
                            "surface_flag": smap_sf,
                        },
                    }
                },
            },
        }
    )
    power_ds = map_ghs_dataset_payload(
        {
            "dataset_id": "ghs-power",
            "source_id": "nasa_power",
            "provider": "nasa_power",
            "product": "NASA_POWER_DAILY",
            "variables": {
                "T2M": {
                    "name": "T2M",
                    "units": "C",
                    "dtype": "float64",
                    "semantics": "continuous_intensive",
                    "nodata": -999.0,
                }
            },
            "spatial_metadata": {"crs": "EPSG:4326", "nominal_resolution_m": 55500.0},
            "temporal_metadata": common_temporal,
            "extensions": {
                "time_series": {
                    "T2M": {
                        "timestamps": timestamps,
                        "values": t2m_vals,
                        "is_scaled": True,
                    }
                }
            },
        }
    )

    req = AssessmentRequest(
        request_id="ghs-e2e-integration",
        analysis_start=datetime(2020, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        qa_policy=QaPolicyLevel.STANDARD,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2022, 12, 31, tzinfo=UTC),
            min_years_required=3,
            min_samples_per_bin=3,
        ),
        spatial=SpatialConfig(region_name="Integration Basin", area_km2=500.0),
    )
    result = ScientificAssessmentService().run_assessment(
        req, datasets=[mod13_ds, imerg_ds, smap_ds, power_ds]
    )
    assert result.status in {AssessmentStatus.COMPLETED, AssessmentStatus.COMPLETED_PARTIAL}
    vars_done = {s.variable_name for s in result.resilience}
    assert {"NDVI", "precipitation", "soil_moisture", "T2M"} <= vars_done
