"""Unit tests for deterministic multi-granule merging and baseline non-leakage."""

from datetime import UTC, datetime

from terra_scientific.adapters.ghs import map_ghs_dataset_payload
from terra_scientific.domain.enums import AssessmentStatus, BaselineType, TemporalCadence
from terra_scientific.domain.models.request import AssessmentRequest, BaselineConfig
from terra_scientific.pipeline.merging import merge_compatible_datasets
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def _mod11a2_payload(
    dataset_id: str,
    timestamps: list[str],
    values: list[float | None],
    *,
    units: str = "K",
    retrieval_timestamp: str = "2025-01-01T00:00:00Z",
) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "source_id": "modis_terra_lst",
        "provider": "nasa_earthdata",
        "product": "MOD11A2.061",
        "retrieval_timestamp": retrieval_timestamp,
        "variables": {
            "LST_Day_1km": {
                "name": "LST_Day_1km",
                "units": units,
                "dtype": "uint16",
                "scale_factor": 0.02,
                "add_offset": 0.0,
                "nodata": 0,
            }
        },
        "spatial_metadata": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": 1000.0,
            "bounds": [0.0, 0.0, 10000.0, 10000.0],
        },
        "temporal_metadata": {
            "start": timestamps[0],
            "end": timestamps[-1],
            "cadence": "eight_day",
            "semantics": "composite",
            "composite_days": 8,
        },
        "extensions": {
            "time_series": {
                "LST_Day_1km": {
                    "timestamps": timestamps,
                    "values": values,
                    "qa_values": {"QC_Day": [0 for _ in timestamps]},
                }
            }
        },
    }


def test_merge_compatible_mod11a2_granules_deduplicates_and_preserves_provenance() -> None:
    ds1 = map_ghs_dataset_payload(
        _mod11a2_payload(
            "11111111-1111-1111-1111-111111111111",
            ["2024-06-01T00:00:00Z", "2024-06-09T00:00:00Z"],
            [14700.0, 14800.0],
            retrieval_timestamp="2025-01-01T00:00:00Z",
        )
    )
    ds2 = map_ghs_dataset_payload(
        _mod11a2_payload(
            "22222222-2222-2222-2222-222222222222",
            ["2024-06-09T00:00:00Z", "2024-06-17T00:00:00Z", "2024-06-25T00:00:00Z"],
            [14810.0, 14900.0, 14950.0],
            retrieval_timestamp="2025-01-02T00:00:00Z",
        )
    )

    merged, _, warnings = merge_compatible_datasets([ds1, ds2])
    assert warnings == []
    assert len(merged) == 1
    series = merged[0].series["LST_Day_1km"]
    assert len(series.timestamps) == 4
    # Overlapping 2024-06-09 resolves deterministically to newer retrieval_timestamp (ds2)
    assert series.values[1] == 14810.0
    assert any(
        "deduplicated 1 overlapping timestamp" in n.lower() for n in merged[0].provenance_notes
    )
    assert any("22222222-2222-2222-2222-222222222222" in n for n in merged[0].provenance_notes)


def test_merge_rejects_incompatible_units() -> None:
    ds1 = map_ghs_dataset_payload(
        _mod11a2_payload(
            "11111111-1111-1111-1111-111111111111",
            ["2024-06-01T00:00:00Z"],
            [14700.0],
            units="K",
        )
    )
    ds2 = map_ghs_dataset_payload(
        _mod11a2_payload(
            "22222222-2222-2222-2222-222222222222",
            ["2024-06-09T00:00:00Z"],
            [25.0],
            units="degC",
        )
    )

    merged, _, warnings = merge_compatible_datasets([ds1, ds2])
    assert len(merged) == 2
    assert any("incompatible variable" in w.lower() for w in warnings)


def test_multi_granule_assessment_merges_and_enforces_explicit_baseline() -> None:
    datasets = [
        map_ghs_dataset_payload(
            _mod11a2_payload(
                f"00000000-0000-0000-0000-00000000000{i}",
                [ts],
                [val],
            )
        )
        for i, (ts, val) in enumerate(
            [
                ("2024-06-01T00:00:00Z", 14700.0),
                ("2024-06-09T00:00:00Z", 14800.0),
                ("2024-06-17T00:00:00Z", 14850.0),
                ("2024-06-25T00:00:00Z", 14900.0),
                ("2024-07-03T00:00:00Z", 14950.0),
                ("2024-07-11T00:00:00Z", 15000.0),
            ],
            start=1,
        )
    ]

    # Fixed reference 2018-2020 must NOT silently fall back to full_period_explicit
    fixed_req = AssessmentRequest(
        request_id="multi-granule-fixed-test",
        analysis_start=datetime(2024, 6, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 7, 31, tzinfo=UTC),
        target_cadence=TemporalCadence.EIGHT_DAY,
        baseline=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2018, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
        ),
    )
    fixed_res = ScientificAssessmentService().run_assessment(fixed_req, datasets=datasets)
    assert len(fixed_res.temporal_series) == 1
    assert len(fixed_res.temporal_series[0].timestamps) == 6
    assert (
        fixed_res.quality_reports[
            "00000000-0000-0000-0000-000000000001:LST_Day_1km"
        ].valid_observations
        == 6
    )
    assert fixed_res.baselines[0].baseline_type == BaselineType.FIXED_REFERENCE
    assert fixed_res.baselines[0].sufficient is False
    # Trend stage had 6 valid observations so overall status is COMPLETED_PARTIAL (not COMPLETED)
    assert fixed_res.status == AssessmentStatus.COMPLETED_PARTIAL
