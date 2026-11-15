"""Integration test verifying GHS -> Scientific Core payload mapping & readiness E2E."""

from datetime import UTC, datetime

from terra_scientific.adapters.ghs import map_ghs_dataset_payload
from terra_scientific.domain.enums import AssessmentStatus, BaselineType, TemporalCadence
from terra_scientific.domain.models.request import (
    AssessmentRequest,
    BaselineConfig,
    TrendConfig,
)
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def test_ghs_harmonized_multi_variable_power_and_modis_flow_to_scientific_result() -> None:
    months = []
    modis_ndvi = []
    modis_qa = []
    power_precip = []
    power_t2m = []
    for yr in range(2020, 2024):
        for mo in range(1, 13):
            months.append(f"{yr:04d}-{mo:02d}-01T00:00:00Z")
            seasonal = 0.25 if mo in (6, 7, 8) else 0.05
            modis_ndvi.append(round(0.45 + seasonal - 0.02 * (yr - 2020), 4))
            modis_qa.append(0)
            power_precip.append(95.0 if mo in (6, 7, 8) else 45.0)
            power_t2m.append(22.0 if mo in (6, 7, 8) else 5.0)

    modis_payload = {
        "dataset_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "source_id": "modis_terra_vegetation",
        "provider": "modis",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "granule_id": "MOD13Q1.A2020001.h19v04.061+47",
        "units": {"NDVI": "dimensionless"},
        "variables": {
            "NDVI": {
                "name": "NDVI",
                "units": "dimensionless",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_intensive",
                "valid_range": [-0.2, 1.0],
                "attributes": {"is_scaled": True},
            }
        },
        "spatial_metadata": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": 250.0,
            "bounds": [0.0, 0.0, 5000.0, 5000.0],
        },
        "temporal_metadata": {
            "start": months[0],
            "end": months[-1],
            "cadence": "monthly",
            "semantics": "interval",
            "aggregation": "mean",
        },
        "quality_metadata": {"qa_layers": ["pixel_reliability"]},
        "assets": [],
        "provenance": {"retrieval_timestamp": "2026-01-01T00:00:00Z"},
        "extensions": {
            "time_series": {
                "NDVI": {
                    "timestamps": months,
                    "values": modis_ndvi,
                    "units": "dimensionless",
                    "qa_layers": {"pixel_reliability": modis_qa},
                    "valid_pixel_counts": [100] * len(months),
                    "total_pixel_counts": [100] * len(months),
                    "is_scaled": True,
                }
            }
        },
    }

    power_payload = {
        "dataset_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "source_id": "nasa_power_agroclimatology",
        "provider": "nasa_power",
        "product": "power_daily",
        "product_version": "v2",
        "granule_id": "POWER_multi",
        "units": {"PRECTOTCORR": "mm", "T2M": "degC"},
        "variables": {
            "PRECTOTCORR": {
                "name": "PRECTOTCORR",
                "units": "mm",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_extensive",
                "attributes": {"is_scaled": True},
            },
            "T2M": {
                "name": "T2M",
                "units": "degC",
                "dtype": "float32",
                "dimensions": ["time"],
                "semantics": "continuous_intensive",
                "attributes": {"is_scaled": True},
            },
        },
        "spatial_metadata": {
            "crs": "EPSG:4326",
            "nominal_resolution_m": 55000.0,
            "bounds": [30.0, 50.0, 31.0, 51.0],
        },
        "temporal_metadata": {
            "start": months[0],
            "end": months[-1],
            "cadence": "monthly",
            "semantics": "interval",
            "aggregation": "sum",
        },
        "quality_metadata": {},
        "assets": [],
        "provenance": {"retrieval_timestamp": "2026-01-01T00:00:00Z"},
        "extensions": {
            "time_series": {
                "PRECTOTCORR": {
                    "timestamps": months,
                    "values": power_precip,
                    "units": "mm",
                    "is_scaled": True,
                },
                "T2M": {
                    "timestamps": months,
                    "values": power_t2m,
                    "units": "degC",
                    "is_scaled": True,
                },
            }
        },
    }

    datasets = [map_ghs_dataset_payload(modis_payload), map_ghs_dataset_payload(power_payload)]
    req = AssessmentRequest(
        request_id="e2e-ghs-sci-1",
        analysis_start=datetime(2023, 1, 1, tzinfo=UTC),
        analysis_end=datetime(2023, 12, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.MONTHLY,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            reference_start=datetime(2020, 1, 1, tzinfo=UTC),
            reference_end=datetime(2022, 12, 31, tzinfo=UTC),
            min_reference_years=3,
            min_samples_per_period=2,
        ),
        trend=TrendConfig(min_samples=12, use_seasonal_mk=True),
    )

    result = ScientificAssessmentService().run_assessment(req, datasets=datasets)
    assert result.status in {AssessmentStatus.COMPLETED, AssessmentStatus.COMPLETED_PARTIAL}
    assert result.readiness is not None
    assert result.readiness.overall_status in {"ready", "partial"}
    assert result.baselines
    assert result.anomalies
    assert result.trends
    assert result.cross_variable is not None
