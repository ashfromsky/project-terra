"""Unit tests for GHS-to-Scientific-Core adapter and dataset loaders."""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from terra_scientific.adapters.ghs import LocalArtifactDatasetLoader, map_ghs_dataset_payload
from terra_scientific.domain.enums import (
    AssessmentStatus,
    DataSourceId,
    TemporalCadence,
    TemporalSemantics,
)
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.pipeline.service import ScientificAssessmentService
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def test_map_ghs_mod13q1_payload_preserves_provenance_scale_and_fill() -> None:
    payload: dict[str, object] = {
        "dataset_id": "11111111-1111-1111-1111-111111111111",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "granule_id": "MOD13Q1.A2020001.h19v04.061",
        "units": {"NDVI": "dimensionless", "EVI": "dimensionless"},
        "variables": {
            "NDVI": {
                "name": "NDVI",
                "units": "dimensionless",
                "dtype": "int16",
                "dimensions": ["time", "y", "x"],
                "semantics": "continuous_intensive",
                "nodata": -3000,
                "scale_factor": 0.0001,
                "add_offset": 0.0,
                "valid_range": [-2000, 10000],
                "attributes": {"is_scaled": False},
            },
        },
        "spatial_metadata": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": 250.0,
            "bounds": [0.0, 0.0, 1000.0, 1000.0],
        },
        "temporal_metadata": {
            "start": "2020-01-01T00:00:00Z",
            "end": "2020-01-17T00:00:00Z",
            "cadence": "sixteen_day",
            "semantics": "composite",
            "composite_days": 16,
        },
        "quality_metadata": {"qa_layers": ["pixel_reliability", "VI_Quality"]},
        "assets": [
            {
                "asset_id": "22222222-2222-2222-2222-222222222222",
                "uri": "s3://terra/mod13q1/ndvi.tif",
                "storage_key": "derived/mod13q1/ndvi.tif",
                "zone": "derived",
                "data_format": "geotiff",
                "media_type": "image/tiff",
            }
        ],
        "provenance": {
            "retrieval_timestamp": "2025-01-10T12:00:00Z",
            "processing_steps": ["decoded_hdf4", "qa_attached"],
        },
        "extensions": {},
    }
    ds = map_ghs_dataset_payload(payload)
    assert ds.source_id == DataSourceId.MODIS_MOD13Q1
    assert ds.product == "MOD13Q1.061"
    assert ds.product_version == "061"
    assert ds.ghs_dataset_id == "11111111-1111-1111-1111-111111111111"
    assert ds.temporal_metadata.cadence == TemporalCadence.SIXTEEN_DAY
    assert ds.temporal_metadata.semantics == TemporalSemantics.COMPOSITE
    assert ds.temporal_metadata.composite_days == 16
    assert ds.variables["NDVI"].scale_factor == pytest.approx(0.0001)
    assert ds.variables["NDVI"].is_scaled is False
    assert -3000.0 in ds.variables["NDVI"].fill_values
    assert ds.raster_refs["NDVI"] == "derived/mod13q1/ndvi.tif"


def test_map_ghs_rejects_gibs_and_preserves_imerg_run_type() -> None:
    gibs_payload: dict[str, object] = {
        "dataset_id": "gibs-id",
        "source_id": "nasa_gibs",
        "provider": "nasa_gibs",
        "product": "MODIS_Terra_CorrectedReflectance_TrueColor",
        "temporal_metadata": {
            "start": "2020-01-01T00:00:00Z",
            "end": "2020-01-02T00:00:00Z",
            "cadence": "daily",
            "semantics": "instantaneous",
        },
        "spatial_metadata": {"crs": "EPSG:4326"},
        "variables": {},
    }
    with pytest.raises(ScientificInputError, match="GIBS"):
        map_ghs_dataset_payload(gibs_payload)

    imerg_payload: dict[str, object] = {
        "dataset_id": "imerg-id",
        "source_id": "gpm_imerg",
        "provider": "nasa_earthdata",
        "product": "GPM_3IMERGHH.07",
        "product_version": "07",
        "temporal_metadata": {
            "start": "2020-06-01T00:00:00Z",
            "end": "2020-06-02T00:00:00Z",
            "cadence": "half_hourly",
            "semantics": "interval",
        },
        "spatial_metadata": {"crs": "EPSG:4326", "nominal_resolution_m": 11132.0},
        "variables": {
            "Grid/precipitation": {
                "name": "Grid/precipitation",
                "units": "mm/hr",
                "semantics": "continuous_intensive",
                "nodata": -9999.9,
            }
        },
        "extensions": {"run_type": "Final"},
    }
    imerg_ds = map_ghs_dataset_payload(imerg_payload)
    assert imerg_ds.source_id == DataSourceId.GPM_IMERG
    assert imerg_ds.run_type == "Final"


def test_local_artifact_dataset_loader_reads_json_series_and_npz_grid(tmp_path: Path) -> None:
    npz_path = tmp_path / "ndvi_stack.npz"
    arr = np.full((2, 4, 4), 0.5, dtype=np.float64)
    qa = np.zeros((2, 4, 4), dtype=np.int64)
    np.savez(npz_path, data=arr, pixel_reliability=qa)

    manifest = {
        "dataset_id": "local-mod13",
        "source_id": "modis_mod13q1",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "provider": "nasa_earthdata",
        "spatial_support": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": 250.0,
            "grid_shape": [4, 4],
            "is_projected": True,
            "pixel_area_m2": 62500.0,
        },
        "temporal_metadata": {
            "cadence": "sixteen_day",
            "semantics": "composite",
            "composite_days": 16,
            "start": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
            "end": datetime(2020, 1, 17, tzinfo=UTC).isoformat(),
        },
        "variables": {
            "NDVI": {
                "name": "NDVI",
                "canonical_name": "ndvi",
                "units": "dimensionless",
                "semantic_kind": "continuous_intensive",
                "scale_factor": 0.0001,
                "is_scaled": True,
                "fill_values": [-3000.0],
                "valid_range": [-0.2, 1.0],
            }
        },
        "raster_refs": {"NDVI": str(npz_path)},
        "series": {
            "NDVI": {
                "timestamps": [
                    "2020-01-01T00:00:00Z",
                    "2020-01-17T00:00:00Z",
                ],
                "values": [0.5, 0.52],
                "qa_layers": {"pixel_reliability": [0, 0]},
                "metadata": {
                    "name": "NDVI",
                    "canonical_name": "ndvi",
                    "units": "dimensionless",
                    "semantic_kind": "continuous_intensive",
                    "scale_factor": 0.0001,
                    "is_scaled": True,
                    "fill_values": [-3000.0],
                    "valid_range": [-0.2, 1.0],
                },
            }
        },
    }
    manifest_path = tmp_path / "dataset.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loader = LocalArtifactDatasetLoader(base_dir=tmp_path)
    dataset = loader.load_dataset(str(manifest_path))
    assert dataset.dataset_id == "local-mod13"
    stack = loader.load_grid_stack(dataset, "NDVI")
    assert stack is not None
    assert stack.data.shape == (2, 4, 4)
    assert "pixel_reliability" in stack.qa_arrays


def test_map_ghs_payload_resolves_aliases_pqi_milli_and_preserves_pre_scaled() -> None:
    from terra_scientific.domain.enums import QaPolicyLevel
    from terra_scientific.quality.validator import screen_dataset_variable

    modis_payload: dict[str, object] = {
        "dataset_id": "33333333-3333-3333-3333-333333333333",
        "source_id": "modis_terra_vegetation",
        "provider": "nasa_earthdata",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "variables": {
            "250m 16 days NDVI": {
                "name": "250m 16 days NDVI",
                "units": "dimensionless",
                "dtype": "float32",
                "semantics": "continuous_intensive",
                "nodata": -3000.0,
                "scale_factor": 0.0001,
                "valid_range": [-0.2, 1.0],
                "attributes": {"is_scaled": False},
            }
        },
        "spatial_metadata": {"crs": MODIS_SINUSOIDAL_WKT, "nominal_resolution_m": 250.0},
        "temporal_metadata": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-02T00:00:00Z",
            "cadence": "sixteen_day",
            "semantics": "composite",
            "composite_days": 16,
        },
        "extensions": {
            "time_series": {
                "NDVI": {
                    "timestamps": ["2026-01-01T00:00:00Z", "2026-01-17T00:00:00Z"],
                    "values": [0.55, 0.62],
                    "is_scaled": True,
                    "qa_layers": {"pixel_reliability": [0, 0]},
                }
            }
        },
    }
    modis_ds = map_ghs_dataset_payload(modis_payload)
    assert "NDVI" in modis_ds.series
    vals, summary = screen_dataset_variable(modis_ds, "NDVI", QaPolicyLevel.STANDARD)
    assert vals.tolist() == [pytest.approx(0.55), pytest.approx(0.62)]
    assert summary.valid_observations == 2

    imerg_payload: dict[str, object] = {
        "dataset_id": "44444444-4444-4444-4444-444444444444",
        "source_id": "gpm_imerg",
        "provider": "nasa_earthdata",
        "product": "GPM_3IMERGHH.07",
        "product_version": "07",
        "variables": {
            "Grid/precipitation": {
                "name": "Grid/precipitation",
                "units": "mm/hr",
                "dtype": "float32",
                "semantics": "continuous_extensive",
                "nodata": -9999.9,
            }
        },
        "spatial_metadata": {"crs": "EPSG:4326", "nominal_resolution_m": 11132.0},
        "temporal_metadata": {
            "start": "2026-07-10T00:00:00Z",
            "end": "2026-07-10T01:00:00Z",
            "cadence": "half_hourly",
            "semantics": "interval",
        },
        "extensions": {
            "run_type": "Final",
            "time_series": {
                "precipitation": {
                    "timestamps": ["2026-07-10T00:00:00Z", "2026-07-10T00:30:00Z"],
                    "values": [8.0, 5.0],
                    "is_scaled": True,
                    "qa_layers": {"precipitationQualityIndex": [0.85, 0.2]},
                }
            },
        },
    }
    imerg_ds = map_ghs_dataset_payload(imerg_payload)
    assert imerg_ds.series["precipitation"].qa_layers["pqi_milli"] == [850, 200]
    imerg_vals_std, _ = screen_dataset_variable(imerg_ds, "precipitation", QaPolicyLevel.STANDARD)
    assert imerg_vals_std[0] == pytest.approx(8.0)
    assert imerg_vals_std[1] == pytest.approx(5.0)

    imerg_vals, imerg_summary = screen_dataset_variable(
        imerg_ds, "precipitation", QaPolicyLevel.STRICT
    )
    assert imerg_vals[0] == pytest.approx(8.0)
    assert np.isnan(imerg_vals[1])
    assert imerg_summary.filtered_by_qa == 1


def test_map_ghs_mod11a2_handles_none_numeric_metadata_and_quality_fields() -> None:
    payload: dict[str, object] = {
        "dataset_id": "55555555-5555-5555-5555-555555555555",
        "source_id": "modis_terra_lst",
        "provider": "nasa_earthdata",
        "product": "MOD11A2.061",
        "product_version": "061",
        "units": {"LST_Day_1km": "K"},
        "variables": {
            "LST_Day_1km": {
                "name": "LST_Day_1km",
                "units": "K",
                "dtype": "uint16",
                "dimensions": ["time", "y", "x"],
                "semantics": "continuous_intensive",
                "nodata": None,
                "scale_factor": None,
                "add_offset": None,
                "valid_range": [None, None],
                "attributes": {},
            },
            "Extra_Diagnostic_SDS": {
                "name": "Extra_Diagnostic_SDS",
                "units": "dimensionless",
                "dtype": "uint8",
                "dimensions": ["time", "y", "x"],
                "semantics": "continuous_intensive",
            },
        },
        "spatial_metadata": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": None,
            "resolution_x": None,
            "bounds": [0.0, 0.0, None, None],
        },
        "temporal_metadata": {
            "start": "2024-06-01T00:00:00Z",
            "end": "2024-06-17T00:00:00Z",
            "cadence": "eight_day",
            "semantics": "composite",
            "composite_days": None,
        },
        "quality_metadata": {
            "valid_pixel_count": None,
            "masked_pixel_count": None,
            "valid_fraction": None,
            "qa_summary": None,
        },
        "extensions": {
            "time_series": {
                "LST_Day_1km": {
                    "timestamps": [
                        "2024-06-01T00:00:00Z",
                        "2024-06-09T00:00:00Z",
                        "2024-06-17T00:00:00Z",
                    ],
                    "values": [14800.0, None, 14950.0],
                    "qa_values": {"QC_Day": [0, 0, 0]},
                }
            }
        },
    }

    dataset = map_ghs_dataset_payload(payload)
    assert dataset.source_id == DataSourceId.MODIS_MOD11A2
    assert "LST_Day_1km" in dataset.variables
    assert "Extra_Diagnostic_SDS" not in dataset.variables
    assert dataset.variables["LST_Day_1km"].scale_factor == pytest.approx(0.02)
    assert dataset.spatial_support.nominal_resolution_m == pytest.approx(1000.0)
    assert dataset.temporal_metadata.composite_days == 1
    assert dataset.series["LST_Day_1km"].values == [14800.0, None, 14950.0]


def test_short_window_assessment_adapts_baseline_for_mod11a2() -> None:
    payload: dict[str, object] = {
        "dataset_id": "66666666-6666-6666-6666-666666666666",
        "source_id": "modis_terra_lst",
        "provider": "nasa_earthdata",
        "product": "MOD11A2.061",
        "variables": {
            "LST_Day_1km": {
                "name": "LST_Day_1km",
                "units": "K",
                "dtype": "uint16",
                "scale_factor": None,
                "add_offset": None,
                "nodata": None,
            }
        },
        "spatial_metadata": {
            "crs": MODIS_SINUSOIDAL_WKT,
            "nominal_resolution_m": None,
            "bounds": [0.0, 0.0, 10000.0, 10000.0],
        },
        "temporal_metadata": {
            "start": "2024-06-01T00:00:00Z",
            "end": "2024-07-15T00:00:00Z",
            "cadence": "eight_day",
            "semantics": "composite",
            "composite_days": None,
        },
        "extensions": {
            "time_series": {
                "LST_Day_1km": {
                    "timestamps": [
                        "2024-06-01T00:00:00Z",
                        "2024-06-09T00:00:00Z",
                        "2024-06-17T00:00:00Z",
                        "2024-07-01T00:00:00Z",
                        "2024-07-09T00:00:00Z",
                    ],
                    "values": [14700.0, 14800.0, 14850.0, 14900.0, 14950.0],
                    "qa_values": {"QC_Day": [0, 0, 0, 0, 0]},
                }
            }
        },
    }

    dataset = map_ghs_dataset_payload(payload)
    request = AssessmentRequest(
        request_id="short-window-mod11a2",
        analysis_start=datetime(2024, 6, 1, tzinfo=UTC),
        analysis_end=datetime(2024, 7, 31, tzinfo=UTC),
    )

    result = ScientificAssessmentService().run_assessment(request, datasets=[dataset])
    assert result.status in {AssessmentStatus.COMPLETED, AssessmentStatus.COMPLETED_PARTIAL}
    assert len(result.baselines) == 1
    assert len(result.anomalies) == 1
    assert any("full-period baseline" in note.lower() for note in result.baselines[0].warnings)
    assert any(np.isfinite(val) for val in result.anomalies[0].standard_zscores if val is not None)
