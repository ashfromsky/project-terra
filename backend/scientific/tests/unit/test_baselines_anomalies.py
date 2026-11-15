"""Unit tests for seasonal climatologies, leakage guards, and anomaly detection."""

from datetime import UTC, datetime

import numpy as np
import pytest

from terra_scientific.anomalies.detector import detect_anomalies
from terra_scientific.baselines.climatology import compute_climatology
from terra_scientific.domain.enums import BaselineType, SeasonalGrouping
from terra_scientific.domain.exceptions import InsufficientDataError
from terra_scientific.domain.models.request import AnomalyConfig, BaselineConfig


def _monthly_fixture() -> tuple[list[datetime], list[float | None]]:
    timestamps: list[datetime] = []
    values: list[float | None] = []
    # 5 baseline years (2015-2019) + 2 assessment years (2020-2021)
    for year in range(2015, 2022):
        for month in range(1, 13):
            timestamps.append(datetime(year, month, 1, tzinfo=UTC))
            base = 0.4 + 0.1 * ((year - 2015) % 3 - 1) * 0.2
            if month in {6, 7, 8}:
                base += 0.2
            if year == 2020 and month in {6, 7, 8}:
                # Inject pronounced negative drought-like NDVI departure in summer 2020
                base -= 0.25
            values.append(round(base, 4))
    return timestamps, values


def test_climatology_separates_baseline_from_assessment_and_handles_insufficient_bins() -> None:
    ts, vals = _monthly_fixture()
    cfg = BaselineConfig(
        baseline_type=BaselineType.FIXED_REFERENCE,
        start=datetime(2015, 1, 1, tzinfo=UTC),
        end=datetime(2019, 12, 31, tzinfo=UTC),
        seasonal_grouping=SeasonalGrouping.CALENDAR_MONTH,
        min_years_required=3,
        min_samples_per_bin=3,
    )
    clim = compute_climatology(
        timestamps=ts,
        values=vals,
        config=cfg,
        variable_name="NDVI",
        units="dimensionless",
        dataset_id="mod13-1",
    )
    assert clim.sufficient is True
    assert len(clim.bins) == 12
    june_bin = next(b for b in clim.bins if b.bin_key == 6)
    assert june_bin.sample_count == 5
    # Baseline years 2015..2019 must exclude the 2020 summer drop (~0.35 vs ~0.60)
    assert june_bin.median == pytest.approx(0.6, abs=0.03)
    assert june_bin.mad is not None and june_bin.mad > 0

    insufficient_cfg = BaselineConfig(
        baseline_type=BaselineType.FIXED_REFERENCE,
        start=datetime(2015, 1, 1, tzinfo=UTC),
        end=datetime(2016, 12, 31, tzinfo=UTC),
        min_years_required=4,
        min_samples_per_bin=3,
    )
    with pytest.raises(InsufficientDataError):
        compute_climatology(
            timestamps=ts,
            values=vals,
            config=insufficient_cfg,
            variable_name="NDVI",
            units="dimensionless",
            raise_on_insufficient=True,
        )


def test_leakage_guard_excludes_assessment_period_when_overlapping() -> None:
    ts, vals = _monthly_fixture()
    cfg = BaselineConfig(
        baseline_type=BaselineType.FIXED_REFERENCE,
        start=datetime(2015, 1, 1, tzinfo=UTC),
        end=datetime(2020, 12, 31, tzinfo=UTC),
        exclude_assessment_overlap=True,
        min_years_required=3,
        min_samples_per_bin=3,
    )
    clim = compute_climatology(
        timestamps=ts,
        values=vals,
        config=cfg,
        variable_name="NDVI",
        units="dimensionless",
        assessment_start=datetime(2020, 1, 1, tzinfo=UTC),
        assessment_end=datetime(2021, 12, 31, tzinfo=UTC),
    )
    assert clim.sufficient is True
    june_bin = next(b for b in clim.bins if b.bin_key == 6)
    # 2020 excluded by overlap guard => only 2015..2019 remain
    assert june_bin.sample_count == 5
    assert any("overlap" in w.lower() for w in clim.warnings)


def test_anomaly_detection_computes_zscores_percentiles_and_persistent_runs() -> None:
    ts, vals = _monthly_fixture()
    cfg = BaselineConfig(
        baseline_type=BaselineType.FIXED_REFERENCE,
        start=datetime(2015, 1, 1, tzinfo=UTC),
        end=datetime(2019, 12, 31, tzinfo=UTC),
        min_years_required=3,
        min_samples_per_bin=3,
    )
    clim = compute_climatology(
        timestamps=ts,
        values=vals,
        config=cfg,
        variable_name="NDVI",
        units="dimensionless",
    )
    anom = detect_anomalies(
        timestamps=ts,
        values=vals,
        climatology=clim,
        config=AnomalyConfig(zscore_threshold=1.5, min_persistence_steps=3),
    )
    # Check summer 2020 indices (2020-06, 2020-07, 2020-08)
    idx_2020_06 = next(i for i, d in enumerate(ts) if d == datetime(2020, 6, 1, tzinfo=UTC))
    z_val = anom.standard_zscores[idx_2020_06]
    assert z_val is not None and z_val < -2.0
    assert anom.robust_zscores[idx_2020_06] is not None
    assert anom.percentiles[idx_2020_06] is not None
    assert anom.percentiles[idx_2020_06] == pytest.approx(0.0)
    assert any(
        run.polarity == "negative_anomaly" and run.step_count >= 3 for run in anom.persistent_runs
    )


def test_zero_variance_baseline_produces_null_zscore_without_division_error() -> None:
    ts = [datetime(y, 1, 1, tzinfo=UTC) for y in range(2015, 2021)]
    vals: list[float | None] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.8]
    clim = compute_climatology(
        timestamps=ts,
        values=vals,
        config=BaselineConfig(
            baseline_type=BaselineType.FIXED_REFERENCE,
            start=datetime(2015, 1, 1, tzinfo=UTC),
            end=datetime(2019, 12, 31, tzinfo=UTC),
            min_years_required=3,
            min_samples_per_bin=3,
        ),
        variable_name="NDVI",
        units="dimensionless",
    )
    anom = detect_anomalies(timestamps=ts, values=vals, climatology=clim, config=AnomalyConfig())
    assert anom.raw_anomalies[-1] == pytest.approx(0.3)
    assert anom.standard_zscores[-1] is None
    assert anom.robust_zscores[-1] is None
    assert np.isfinite(anom.raw_anomalies[-1])
