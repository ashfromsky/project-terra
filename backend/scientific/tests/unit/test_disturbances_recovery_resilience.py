"""Unit tests for Pettitt change-point, event recovery, and resilience dimensions."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from terra_scientific.disturbances.detector import detect_disturbances
from terra_scientific.domain.enums import StageStatus
from terra_scientific.domain.models.request import DisturbanceConfig, RecoveryConfig
from terra_scientific.recovery.analyzer import analyze_post_event_recovery
from terra_scientific.resilience.metrics import compute_resilience_dimensions


def test_pettitt_detects_step_shift_without_inventing_physical_cause() -> None:
    ts = [datetime(2015, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(40)]
    # Clear negative regime shift at index 20
    vals = np.concatenate([np.full(20, 0.7), np.full(20, 0.35)]) + np.linspace(-0.01, 0.01, 40)
    zscores = np.concatenate([np.zeros(20), np.full(20, -2.5)])

    dist = detect_disturbances(
        ts,
        vals,
        zscores,
        DisturbanceConfig(alpha=0.05, min_segment_length=5, negative_z_threshold=-1.5),
        dataset_id="mod13-cp",
        variable_name="NDVI",
    )
    assert len(dist.change_points) >= 1
    cp = max(dist.change_points, key=lambda item: item.statistic)
    assert 18 <= cp.index <= 21
    assert cp.shift_magnitude < -0.25
    assert cp.classification == "statistical_change_point"
    assert cp.cause_attribution_status == "not_determined_without_external_evidence"


def test_event_recovery_measures_elapsed_rate_and_marks_censored_events() -> None:
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    # 24 monthly steps (~30 days spacing)
    ts = [t0 + timedelta(days=30 * i) for i in range(24)]
    anom = np.zeros(24, dtype=np.float64)
    # Anomaly drops to -0.30 at idx 8 (240d), recovers to 0.0 by idx 14 (420d).
    anom[7] = -0.15
    anom[8] = -0.30
    anom[9:15] = [-0.24, -0.18, -0.12, -0.06, -0.02, 0.0]

    rec_full = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=7,
        event_peak_idx=8,
        config=RecoveryConfig(pre_event_window_steps=6, recovery_fraction_threshold=0.9),
        is_deseasonalized=True,
        unit_label="NDVI",
    )
    assert rec_full.status == "recovered"
    assert rec_full.deficit_magnitude == pytest.approx(0.30)
    assert rec_full.recovery_completeness >= 0.9
    assert rec_full.time_to_recovery_days == pytest.approx(180.0, abs=31.0)
    assert rec_full.elapsed_recovery_rate is not None and rec_full.elapsed_recovery_rate > 0.3

    # Censored series: ends at index 10 at -0.18 (only 40% recovered)
    rec_censored = analyze_post_event_recovery(
        ts[:11],
        anom[:11],
        event_start_idx=7,
        event_peak_idx=8,
        config=RecoveryConfig(
            pre_event_window_steps=6,
            recovery_fraction_threshold=0.9,
            min_post_event_steps=2,
        ),
        is_deseasonalized=True,
        unit_label="NDVI",
    )
    assert rec_censored.status == "incomplete_censored"
    assert rec_censored.recovery_completeness == pytest.approx(0.4, abs=0.05)


def test_resilience_dimensions_withholds_composite_tri_and_separates_four_components() -> None:
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(24)]
    anom = np.zeros(24, dtype=np.float64)
    anom[7:15] = [-0.15, -0.30, -0.24, -0.18, -0.12, -0.06, -0.02, 0.0]
    z = anom / 0.1  # peak z = -3.0

    rec = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=7,
        event_peak_idx=8,
        config=RecoveryConfig(pre_event_window_steps=6),
        is_deseasonalized=True,
        unit_label="NDVI",
    )
    res = compute_resilience_dimensions(
        dataset_id="mod13-res",
        variable_name="NDVI",
        deseasonalized_residuals=anom,
        zscores=z,
        recovery_events=[rec],
        sensitivity_slope=0.45,
        sensitivity_driver="precipitation",
    )
    assert res.resistance.available is True
    assert res.resistance.value == pytest.approx(1.0 / (1.0 + 3.0))
    assert res.recovery.available is True
    assert res.stability.available is True
    assert res.sensitivity.available is True
    assert res.composite_tri.status == "unavailable_unvalidated"
    assert res.composite_tri.value is None

    # No driver -> sensitivity explicitly unavailable, no events -> resistance unavailable
    res_no_event = compute_resilience_dimensions(
        dataset_id="mod13-quiet",
        variable_name="NDVI",
        deseasonalized_residuals=np.random.default_rng(1).normal(0.0, 0.02, 24),
        zscores=np.zeros(24),
        recovery_events=[],
    )
    assert res_no_event.resistance.available is False
    assert res_no_event.resistance.status == StageStatus.UNAVAILABLE
    assert res_no_event.resistance.value is None
    assert res_no_event.sensitivity.status == StageStatus.UNAVAILABLE


def test_resistance_uses_negative_event_peaks_only_and_ignores_positive_shocks() -> None:
    from terra_scientific.domain.models.result import PersistentAnomalyRun

    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(24)]
    anom = np.zeros(24, dtype=np.float64)
    anom[7:11] = [-0.15, -0.20, -0.10, 0.0]
    anom[14:18] = [-0.20, -0.40, -0.15, 0.0]
    z = np.zeros(24, dtype=np.float64)
    z[3] = 8.5  # unrelated huge positive shock outside negative episodes
    z[7:10] = [-1.5, -2.0, -1.0]
    z[14:17] = [-2.0, -4.0, -1.5]

    rec_1 = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=7,
        next_event_idx=14,
        config=RecoveryConfig(pre_event_window_steps=6),
        is_deseasonalized=True,
    )
    rec_2 = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=14,
        config=RecoveryConfig(pre_event_window_steps=4),
        is_deseasonalized=True,
    )
    runs = [
        PersistentAnomalyRun(
            start_timestamp=ts[3],
            end_timestamp=ts[3],
            step_count=1,
            polarity="positive_anomaly",
            peak_zscore=8.5,
            mean_zscore=8.5,
            cumulative_departure=8.5,
        ),
        PersistentAnomalyRun(
            start_timestamp=ts[7],
            end_timestamp=ts[9],
            step_count=3,
            polarity="negative_anomaly",
            peak_zscore=-2.0,
            mean_zscore=-1.5,
            cumulative_departure=-4.5,
        ),
        PersistentAnomalyRun(
            start_timestamp=ts[14],
            end_timestamp=ts[16],
            step_count=3,
            polarity="negative_anomaly",
            peak_zscore=-4.0,
            mean_zscore=-2.5,
            cumulative_departure=-7.5,
        ),
    ]

    res = compute_resilience_dimensions(
        dataset_id="mod13-neg-peaks",
        variable_name="NDVI",
        deseasonalized_residuals=anom,
        standardized_residuals=z,
        zscores=z,
        timestamps=ts,
        disturbance_runs=runs,
        recovery_events=[rec_1, rec_2],
    )
    expected = (1.0 / (1.0 + 2.0) + 1.0 / (1.0 + 4.0)) / 2.0
    assert res.resistance.available is True
    assert res.resistance.status == StageStatus.COMPLETED
    assert res.resistance.value == pytest.approx(expected)
    assert len(res.resistance.event_values) == 2
    assert [ev.peak_negative_zscore for ev in res.resistance.event_values] == [-2.0, -4.0]

    # Positive-only runs must return UNAVAILABLE, not high resistance.
    res_pos_only = compute_resilience_dimensions(
        dataset_id="mod13-pos-only",
        variable_name="NDVI",
        deseasonalized_residuals=anom,
        standardized_residuals=z,
        zscores=z,
        timestamps=ts,
        disturbance_runs=[runs[0]],
        recovery_events=[],
    )
    assert res_pos_only.resistance.available is False
    assert res_pos_only.resistance.status == StageStatus.UNAVAILABLE
    assert res_pos_only.resistance.value is None


def test_stability_is_invariant_across_physical_unit_scales_and_handles_zero_dispersion() -> None:
    rng = np.random.default_rng(7)
    raw_kelvin = rng.normal(0.0, 2.5, 24)
    raw_scaled = raw_kelvin * 1000.0
    std_resid = raw_kelvin / 2.5
    std_resid[2] = np.nan

    res_k = compute_resilience_dimensions(
        dataset_id="era5-k",
        variable_name="t2m",
        deseasonalized_residuals=raw_kelvin,
        standardized_residuals=std_resid,
    )
    res_mk = compute_resilience_dimensions(
        dataset_id="era5-mk",
        variable_name="t2m_mK",
        deseasonalized_residuals=raw_scaled,
        standardized_residuals=std_resid,
    )
    assert res_k.stability.available is True
    assert res_k.stability.value == pytest.approx(res_mk.stability.value)

    res_flat = compute_resilience_dimensions(
        dataset_id="flat",
        variable_name="NDVI",
        deseasonalized_residuals=np.zeros(10),
        standardized_residuals=np.zeros(10),
    )
    assert res_flat.stability.available is True
    assert res_flat.stability.value == pytest.approx(1.0)
    assert any("Zero dispersion" in lim for lim in res_flat.stability.limitations)


def test_recovery_requires_consecutive_confirmation_and_respects_next_event_boundary() -> None:
    ts = [datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(20)]
    anom = np.zeros(20, dtype=np.float64)
    # Trough -0.40 at idx 7; pre_baseline = 0.0; target >= -0.04.
    # Index 9 spikes briefly to -0.01 (1 step), followed by NaN at 10 and dip -0.20 at 11.
    # Confirmed recovery happens only at indices 12-13 (2 consecutive valid steps >= -0.04).
    anom[6:15] = [-0.20, -0.40, -0.25, -0.01, np.nan, -0.20, -0.02, 0.0, 0.0]

    rec_confirmed = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=6,
        event_peak_idx=7,
        config=RecoveryConfig(
            pre_event_window_steps=5,
            recovery_fraction_threshold=0.9,
            min_post_event_steps=2,
            confirmation_steps=2,
        ),
        is_deseasonalized=True,
    )
    assert rec_confirmed.status == "recovered"
    assert rec_confirmed.time_to_recovery_days == pytest.approx((ts[12] - ts[7]).days)
    assert rec_confirmed.time_to_recovery_days > (ts[9] - ts[7]).days
    assert rec_confirmed.observation_end == ts[-1]

    # Next disturbance at idx 11 prevents using recovery at indices 12-13 (right-censored).
    rec_bounded = analyze_post_event_recovery(
        ts,
        anom,
        event_start_idx=6,
        event_peak_idx=7,
        next_event_idx=11,
        config=RecoveryConfig(
            pre_event_window_steps=5,
            recovery_fraction_threshold=0.9,
            min_post_event_steps=2,
            confirmation_steps=2,
        ),
        is_deseasonalized=True,
    )
    assert rec_bounded.status == "incomplete_censored"
    assert rec_bounded.observation_end == ts[9]

    # When trajectory remains depressed before next_event_idx, preserve not_recovered.
    anom_flat = anom.copy()
    anom_flat[8:11] = [-0.40, -0.40, np.nan]
    rec_not_recovered = analyze_post_event_recovery(
        ts,
        anom_flat,
        event_start_idx=6,
        event_peak_idx=7,
        next_event_idx=11,
        config=RecoveryConfig(
            pre_event_window_steps=5,
            recovery_fraction_threshold=0.9,
            min_post_event_steps=2,
            confirmation_steps=2,
        ),
        is_deseasonalized=True,
    )
    assert rec_not_recovered.status == "not_recovered"
    assert rec_not_recovered.observation_end == ts[9]

    # Missing pre-event window produces insufficient_data rather than fabricating baseline 0.
    anom_missing_pre = anom.copy()
    anom_missing_pre[:6] = np.nan
    rec_missing_pre = analyze_post_event_recovery(
        ts,
        anom_missing_pre,
        event_start_idx=6,
        event_peak_idx=7,
        config=RecoveryConfig(pre_event_window_steps=5),
        is_deseasonalized=True,
    )
    assert rec_missing_pre.status == "insufficient_data"
