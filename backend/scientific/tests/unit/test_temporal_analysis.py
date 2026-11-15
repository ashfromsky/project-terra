"""Unit tests for source-aware temporal conversion, aggregation, and interpolation."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from terra_scientific.domain.enums import (
    AggregationOperator,
    DataSourceId,
    SeasonalGrouping,
    TemporalCadence,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import TemporalAlignmentError
from terra_scientific.domain.models.dataset import VariableMetadata
from terra_scientific.temporal.aggregation import (
    aggregate_temporal_series,
    integrate_imerg_half_hourly_day,
    kelvin_to_celsius,
)
from terra_scientific.temporal.interpolation import interpolate_gaps_explicit
from terra_scientific.temporal.seasonal import seasonal_group_keys


def test_imerg_half_hourly_rate_converts_to_depth_and_never_turns_missing_into_zero() -> None:
    # 48 half-hour intervals in one UTC day: 4 mm/hr constant => 2 mm per 30 min => 96 mm/day
    rates = np.full(48, 4.0, dtype=np.float64)
    depth_mm, valid_cnt, exp_cnt, cov = integrate_imerg_half_hourly_day(rates, min_coverage=0.7)
    assert depth_mm == pytest.approx(96.0)
    assert valid_cnt == 48
    assert exp_cnt == 48
    assert cov == pytest.approx(1.0)

    # Below 70% valid coverage must remain None rather than zero or partial sum.
    sparse_rates = np.full(48, np.nan, dtype=np.float64)
    sparse_rates[:20] = 0.0
    sparse_depth, valid_s, _, cov_s = integrate_imerg_half_hourly_day(
        sparse_rates, min_coverage=0.7
    )
    assert sparse_depth is None
    assert valid_s == 20
    assert cov_s == pytest.approx(20 / 48)


def test_aggregate_temporal_series_forbids_summing_intensive_ndvi_and_integrates_imerg() -> None:
    ndvi_meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    ts = [datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 17, tzinfo=UTC)]
    vals = np.array([0.4, 0.5], dtype=np.float64)

    with pytest.raises(TemporalAlignmentError, match="intensive"):
        aggregate_temporal_series(
            values=vals,
            timestamps=ts,
            metadata=ndvi_meta,
            target_cadence=TemporalCadence.MONTHLY,
            operator=AggregationOperator.SUM,
        )

    monthly_ndvi = aggregate_temporal_series(
        values=vals,
        timestamps=ts,
        metadata=ndvi_meta,
        target_cadence=TemporalCadence.MONTHLY,
        operator=AggregationOperator.MEAN,
        expected_steps_per_period=2,
        min_coverage=0.5,
    )
    assert monthly_ndvi.values == [pytest.approx(0.45)]
    assert monthly_ndvi.valid_subintervals == [2]

    # Two days of 30-min IMERG rates: day 1 valid @ 2 mm/hr = 48 mm, day 2 missing -> None.
    t0 = datetime(2020, 6, 1, 0, 0, tzinfo=UTC)
    imerg_ts = [t0 + timedelta(minutes=30 * i) for i in range(96)]
    imerg_rates = np.full(96, np.nan, dtype=np.float64)
    imerg_rates[:48] = 2.0
    imerg_meta = VariableMetadata(
        name="Grid/precipitation",
        canonical_name="precipitation_rate",
        units="mm/hr",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    daily_precip = aggregate_temporal_series(
        values=imerg_rates,
        timestamps=imerg_ts,
        metadata=imerg_meta,
        target_cadence=TemporalCadence.DAILY,
        operator=AggregationOperator.SUM,
        source_id=DataSourceId.GPM_IMERG,
        min_coverage=0.7,
    )
    assert daily_precip.units == "mm"
    assert daily_precip.values[0] == pytest.approx(48.0)
    assert daily_precip.values[1] is None


def test_kelvin_to_celsius_and_seasonal_doy_binning() -> None:
    celsius = kelvin_to_celsius(np.array([273.15, 300.0, np.nan]))
    assert celsius[0] == pytest.approx(0.0)
    assert celsius[1] == pytest.approx(26.85)
    assert np.isnan(celsius[2])

    dates = [
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 17, tzinfo=UTC),
        datetime(2020, 2, 2, tzinfo=UTC),
    ]
    bins, labels = seasonal_group_keys(dates, SeasonalGrouping.COMPOSITE_DOY_BIN, composite_days=16)
    assert bins == [1, 2, 3]
    assert labels == ["DOY_bin_01", "DOY_bin_02", "DOY_bin_03"]


def test_explicit_interpolation_tracks_indices_and_never_extrapolates() -> None:
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(5)]
    vals = np.array([np.nan, 1.0, np.nan, 3.0, np.nan], dtype=np.float64)
    filled, idx, note = interpolate_gaps_explicit(ts, vals, max_gap_steps=2)
    assert np.isnan(filled[0])
    assert filled[1] == pytest.approx(1.0)
    assert filled[2] == pytest.approx(2.0)
    assert filled[3] == pytest.approx(3.0)
    assert np.isnan(filled[4])
    assert idx == [2]
    assert "linear" in note.lower()
