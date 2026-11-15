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

    # No driver -> sensitivity explicitly unavailable, no events -> resistance skipped
    res_no_event = compute_resilience_dimensions(
        dataset_id="mod13-quiet",
        variable_name="NDVI",
        deseasonalized_residuals=np.random.default_rng(1).normal(0.0, 0.02, 24),
        zscores=np.zeros(24),
        recovery_events=[],
    )
    assert res_no_event.resistance.status == StageStatus.SKIPPED
    assert res_no_event.sensitivity.status == StageStatus.UNAVAILABLE
