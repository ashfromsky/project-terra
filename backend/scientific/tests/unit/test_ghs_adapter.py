"""Unit tests for GHS-to-Scientific-Core adapter and dataset loaders."""

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from terra_scientific.adapters.ghs import LocalArtifactDatasetLoader, map_ghs_dataset_payload
from terra_scientific.domain.enums import (
    DataSourceId,
    TemporalCadence,
    TemporalSemantics,
)
from terra_scientific.domain.exceptions import ScientificInputError
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
