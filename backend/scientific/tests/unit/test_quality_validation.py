"""Unit tests for Scientific Core QA bitmasks, scaling, physical bounds, and source policies."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from terra_scientific.domain.enums import (
    DataSourceId,
    OverpassMode,
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
from terra_scientific.domain.models.temporal import TemporalMetadata
from terra_scientific.quality.validator import screen_dataset_variable
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT


def _mod13_dataset(
    raw_values: list[float | None],
    reliability: list[int | None],
    vi_quality: list[int | None] | None = None,
    *,
    is_scaled: bool = False,
) -> ScientificDataset:
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=16 * i) for i in range(len(raw_values))]
    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.0001,
        is_scaled=is_scaled,
        fill_values=(-3000.0,),
        valid_range=(-0.2, 1.0),
    )
    qa_layers: dict[str, list[int | None]] = {"pixel_reliability": reliability}
    if vi_quality is not None:
        qa_layers["VI_Quality"] = vi_quality
    series = ObservationSeries(timestamps=ts, values=raw_values, qa_layers=qa_layers, metadata=meta)
    return ScientificDataset(
        dataset_id="mod13-test",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.SIXTEEN_DAY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=16,
            start=ts[0],
            end=ts[-1] + timedelta(days=16),
        ),
        variables={"NDVI": meta},
        series={"NDVI": series},
    )


def test_mod13_screens_fill_applies_scale_once_and_filters_qa_strict_vs_standard() -> None:
    ds = _mod13_dataset(
        raw_values=[6000, 5500, 7000, -3000, 15000],
        reliability=[0, 1, 3, -1, 0],
    )
    strict_vals, strict_summary = screen_dataset_variable(ds, "NDVI", QaPolicyLevel.STRICT)
    assert strict_vals[0] == pytest.approx(0.6)
    assert np.isnan(strict_vals[1])  # Marginal excluded under strict
    assert np.isnan(strict_vals[2])  # Cloudy excluded
    assert np.isnan(strict_vals[3])  # Fill excluded
    assert np.isnan(strict_vals[4])  # Out of physical range (> 1.0)
    assert strict_summary.valid_observations == 1
    assert strict_summary.missing_or_fill == 1
    assert strict_summary.out_of_physical_range == 1
    assert strict_summary.filtered_by_qa == 2

    std_vals, std_summary = screen_dataset_variable(ds, "NDVI", QaPolicyLevel.STANDARD)
    assert std_vals[0] == pytest.approx(0.6)
    assert std_vals[1] == pytest.approx(0.55)  # Marginal accepted under standard
    assert std_summary.valid_observations == 2


def test_mod13_vi_quality_bitmask_rejects_adjacent_cloud_and_snow_bits() -> None:
    # bit 8: adjacent cloud (256), bit 14: snow/ice (16384), bit 2..5 usefulness=1 (4)
    ds = _mod13_dataset(
        raw_values=[0.5, 0.52, 0.48, 0.45],
        reliability=[0, 0, 0, 0],
        vi_quality=[0, 256, 16384, 4],  # usefulness=1 (bits 2-5 == 0001 -> 4) is ok
        is_scaled=True,
    )
    vals, summary = screen_dataset_variable(ds, "NDVI", QaPolicyLevel.STANDARD)
    assert vals[0] == pytest.approx(0.5)
    assert np.isnan(vals[1])  # Adjacent cloud rejected
    assert np.isnan(vals[2])  # Snow/ice rejected
    assert vals[3] == pytest.approx(0.45)
    assert summary.filtered_by_qa == 2


def test_mod11_day_night_scaling_and_qc_bitmask() -> None:
    t0 = datetime(2020, 7, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=8 * i) for i in range(4)]
    meta = VariableMetadata(
        name="LST_Day_1km",
        canonical_name="land_surface_temperature_day",
        units="K",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        scale_factor=0.02,
        is_scaled=False,
        fill_values=(0.0,),
        valid_range=(150.0, 380.0),
    )
    # 15000 * 0.02 = 300.0 K; qc=0 clean, qc=128 (bits 6-7=2, >2K error), qc=2 (cloud), 0 fill
    series = ObservationSeries(
        timestamps=ts,
        values=[15000, 14900, 14500, 0],
        qa_layers={"QC_Day": [0, 128, 2, 0]},
        metadata=meta,
    )
    ds = ScientificDataset(
        dataset_id="mod11-test",
        source_id=DataSourceId.MODIS_MOD11A2,
        product="MOD11A2.061",
        product_version="061",
        provider="nasa_earthdata",
        spatial_support=SpatialSupport(crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=1000.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.EIGHT_DAY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=8,
            start=ts[0],
            end=ts[-1] + timedelta(days=8),
        ),
        variables={"LST_Day_1km": meta},
        series={"LST_Day_1km": series},
    )
    vals, summary = screen_dataset_variable(ds, "LST_Day_1km", QaPolicyLevel.STANDARD)
    assert vals[0] == pytest.approx(300.0)
    assert np.isnan(vals[1])  # LST error > 2K rejected in standard policy
    assert np.isnan(vals[2])  # Not produced / cloud rejected
    assert np.isnan(vals[3])  # Fill value 0 masked before scaling
    assert summary.valid_observations == 1


def test_imerg_rejects_early_late_baseline_unless_explicitly_enabled() -> None:
    t0 = datetime(2020, 6, 1, tzinfo=UTC)
    ts = [t0, t0 + timedelta(minutes=30)]
    meta = VariableMetadata(
        name="Grid/precipitation",
        canonical_name="precipitation_rate",
        units="mm/hr",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        fill_values=(-9999.9,),
        valid_range=(0.0, 400.0),
    )
    ds = ScientificDataset(
        dataset_id="imerg-early",
        source_id=DataSourceId.GPM_IMERG,
        product="GPM_3IMERGHH.07",
        product_version="07",
        provider="nasa_earthdata",
        run_type="Early",
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=11132.0),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.HALF_HOURLY,
            semantics=TemporalSemantics.INTERVAL,
            start=ts[0],
            end=ts[-1] + timedelta(minutes=30),
        ),
        variables={"Grid/precipitation": meta},
        series={
            "Grid/precipitation": ObservationSeries(timestamps=ts, values=[4.0, 6.0], metadata=meta)
        },
    )
    with pytest.raises(ScientificInputError, match="Final"):
        screen_dataset_variable(ds, "Grid/precipitation", QaPolicyLevel.STANDARD)

    vals, summary = screen_dataset_variable(
        ds,
        "Grid/precipitation",
        QaPolicyLevel.STANDARD,
        allow_imerg_early_late=True,
    )
    assert vals[0] == pytest.approx(4.0)
    assert any("Early" in w for w in summary.warnings)


def test_smap_filters_retrieval_and_surface_flags_and_separates_overpass() -> None:
    t0 = datetime(2020, 5, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=i) for i in range(4)]
    meta = VariableMetadata(
        name="soil_moisture",
        canonical_name="surface_soil_moisture_am",
        units="cm^3/cm^3",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
        fill_values=(-9999.0,),
        valid_range=(0.02, 0.65),
    )
    series = ObservationSeries(
        timestamps=ts,
        values=[0.22, 0.25, 0.28, 0.24],
        qa_layers={
            "retrieval_qual_flag": [0, 8, 1, 0],  # 0 and 8 clean bit 0; 1 not recommended
            "surface_flag": [0, 0, 0, 4],  # 4 indicates snow/ice/frozen surface contamination
        },
        overpass_tags=["AM", "AM", "AM", "PM"],
        metadata=meta,
    )
    ds = ScientificDataset(
        dataset_id="smap-am",
        source_id=DataSourceId.SMAP_SPL3SMP_E,
        product="SPL3SMP_E.006",
        product_version="006",
        provider="nasa_earthdata",
        overpass_mode=OverpassMode.AM_ONLY,
        spatial_support=SpatialSupport(
            crs="EPSG:6933", nominal_resolution_m=9000.0, native_footprint_m=36000.0
        ),
        temporal_metadata=TemporalMetadata(
            cadence=TemporalCadence.DAILY,
            semantics=TemporalSemantics.COMPOSITE,
            composite_days=1,
            start=ts[0],
            end=ts[-1] + timedelta(days=1),
        ),
        variables={"soil_moisture": meta},
        series={"soil_moisture": series},
    )
    vals, summary = screen_dataset_variable(
        ds, "soil_moisture", QaPolicyLevel.STANDARD, overpass_mode=OverpassMode.AM_ONLY
    )
    assert vals[0] == pytest.approx(0.22)
    assert vals[1] == pytest.approx(0.25)
    assert np.isnan(vals[2])  # retrieval_qual_flag=1 excluded
    assert np.isnan(vals[3])  # PM excluded by AM_ONLY + surface_flag!=0
    assert summary.valid_observations == 2
