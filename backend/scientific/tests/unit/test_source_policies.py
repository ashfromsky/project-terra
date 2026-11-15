"""Unit tests for NASA source adapters, metadata policies, and GIBS rejection."""

import pytest

from terra_scientific.domain.enums import DataSourceId, QaPolicyLevel
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.sources.catalog import (
    assert_quantitative_source_allowed,
    get_qa_policy,
    get_source_spec,
)


def test_mod13q1_spec_preserves_official_scale_fill_qa_and_grid() -> None:
    spec = get_source_spec(DataSourceId.MODIS_MOD13Q1, "MOD13Q1.061")
    assert spec.nominal_resolution_m == 250.0
    assert spec.composite_days == 16
    assert "Sinusoidal" in spec.native_crs
    ndvi = spec.variables["NDVI"]
    evi = spec.variables["EVI"]
    assert ndvi.scale_factor == pytest.approx(0.0001)
    assert evi.scale_factor == pytest.approx(0.0001)
    assert -3000.0 in ndvi.fill_values
    assert ndvi.valid_range == pytest.approx((-0.2, 1.0))
    assert any("saturate" in note.lower() for note in spec.limitations)

    strict = get_qa_policy(DataSourceId.MODIS_MOD13Q1, "MOD13Q1.061", QaPolicyLevel.STRICT)
    assert 0 in strict.accepted_flags
    assert 1 not in strict.accepted_flags
    assert 3 in strict.excluded_flags


def test_imerg_v07_spec_requires_final_for_baseline_and_rate_to_depth_rule() -> None:
    spec = get_source_spec(DataSourceId.GPM_IMERG, "GPM_3IMERGHH.07")
    assert spec.default_variable == "Grid/precipitation"
    assert spec.variables["Grid/precipitation"].units == "mm/hr"
    assert spec.temporal_cadence.value == "half_hourly"
    assert any("0.5" in note for note in spec.limitations)
    assert any("Final" in note for note in spec.limitations)


def test_smap_spec_pins_version_006_separates_am_pm_and_records_36km_footprint() -> None:
    spec = get_source_spec(DataSourceId.SMAP_SPL3SMP_E, "SPL3SMP_E.006")
    assert spec.product_version == "006"
    assert spec.native_crs == "EPSG:6933"
    assert spec.nominal_resolution_m == 9000.0
    assert spec.native_footprint_m == 36000.0
    assert any("root-zone" in note.lower() or "5 cm" in note.lower() for note in spec.limitations)


def test_mod11a2_spec_separates_day_night_and_celsius_caveat() -> None:
    spec = get_source_spec(DataSourceId.MODIS_MOD11A2, "MOD11A2.061")
    assert "LST_Day_1km" in spec.variables
    assert "LST_Night_1km" in spec.variables
    assert spec.variables["LST_Day_1km"].scale_factor == pytest.approx(0.02)
    assert 0.0 in spec.variables["LST_Day_1km"].fill_values
    assert any("air temperature" in note.lower() for note in spec.limitations)


def test_nasa_power_distinguishes_merra2_and_ceres_provenance() -> None:
    spec = get_source_spec(DataSourceId.NASA_POWER, "POWER_DAILY")
    assert spec.variables["T2M"].attributes["origin_dataset"] == "MERRA-2"
    assert spec.variables["ALLSKY_SFC_SW_DWN"].attributes["origin_dataset"] == "CERES_SYN1deg"
    assert any("gpm imerg" in note.lower() for note in spec.limitations)


def test_gibs_is_explicitly_rejected_for_quantitative_use() -> None:
    with pytest.raises(ScientificInputError, match="GIBS"):
        assert_quantitative_source_allowed(DataSourceId.NASA_GIBS, "MODIS_Terra_NDVI")
