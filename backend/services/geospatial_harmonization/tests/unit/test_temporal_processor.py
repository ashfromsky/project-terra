"""Unit tests for temporal alignment, rate-to-depth integration, and coverage masking."""

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest

from geospatial_harmonization.domain.exceptions import (
    IncompatibleDatasetError,
    InvalidTemporalSpecError,
    QualityPolicyViolationError,
)
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.transformations import (
    aggregate_temporal_stack,
    integrate_rate_to_depth,
    normalize_to_utc,
)


def _interval(start_h: int, hours: float = 0.5) -> TemporalSpec:
    t0 = datetime(2026, 7, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=int(start_h * 30))
    return TemporalSpec(t0, t0 + timedelta(seconds=int(hours * 3600)), "30min", "interval")


def test_normalize_to_utc_and_integrate_rate_to_depth_preserves_missing_mask() -> None:
    plus2 = timezone(timedelta(hours=2))
    dt = normalize_to_utc(datetime(2026, 7, 1, 12, 0, tzinfo=plus2))
    assert dt == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    with pytest.raises(InvalidTemporalSpecError, match="timezone-aware"):
        normalize_to_utc(datetime(2026, 7, 1, 12, 0))

    specs = [_interval(0, 0.5), _interval(1, 0.5)]
    target = TemporalSpec(specs[0].start, specs[1].end, "1hour", "interval", "rate_to_depth_sum")
    a0 = np.array([[10.0, 20.0], [-9999.0, -9999.0]], dtype=np.float32)
    a1 = np.array([[6.0, -9999.0], [-9999.0, 4.0]], dtype=np.float32)

    res = integrate_rate_to_depth(
        [a0, a1], specs, target, min_coverage_fraction=0.5, nodata=-9999.0
    )
    assert res.data[0, 0] == pytest.approx(8.0)
    assert res.data[0, 1] == pytest.approx(10.0)
    assert np.isnan(res.data[1, 0])
    assert res.data[1, 1] == pytest.approx(2.0)
    assert res.coverage_fraction[0, 1] == pytest.approx(0.5)
    assert res.valid_pixels == 3

    strict = integrate_rate_to_depth(
        [a0, a1], specs, target, min_coverage_fraction=1.0, nodata=-9999.0
    )
    assert np.isnan(strict.data[0, 1])
    assert strict.valid_pixels == 1


def test_rate_to_depth_rejects_instantaneous_and_supports_weighted_and_composite() -> None:
    t0 = datetime(2026, 7, 1, tzinfo=UTC)
    inst = TemporalSpec(t0, t0, "daily", "instantaneous")
    target = TemporalSpec(t0, t0 + timedelta(days=1), "daily", "interval")

    with pytest.raises(InvalidTemporalSpecError, match="interval"):
        integrate_rate_to_depth([np.ones((2, 2), np.float32)], [inst], target)

    with pytest.raises(QualityPolicyViolationError, match="min_coverage_fraction"):
        integrate_rate_to_depth(
            [np.ones((2, 2), np.float32)], [_interval(0)], target, min_coverage_fraction=1.5
        )

    c0 = TemporalSpec(t0, t0 + timedelta(days=16), "16daily", "composite", composite_days=16)
    c1 = TemporalSpec(
        t0 + timedelta(days=16), t0 + timedelta(days=32), "16daily", "composite", composite_days=16
    )
    comp_target = TemporalSpec(t0, c1.end, "monthly", "interval", "quality_weighted_mean")
    s0 = np.full((2, 2), 0.8, dtype=np.float32)
    s1 = np.full((2, 2), 0.2, dtype=np.float32)
    w0 = np.full((2, 2), 3.0, dtype=np.float32)
    w1 = np.full((2, 2), 1.0, dtype=np.float32)

    w_res = aggregate_temporal_stack(
        [s0, s1], [c0, c1], comp_target, "quality_weighted_mean", weights=[w0, w1]
    )
    assert float(w_res.data[0, 0]) == pytest.approx(0.65)
    assert any("composite" in w.lower() for w in w_res.warnings)

    with pytest.raises(IncompatibleDatasetError, match="weight"):
        aggregate_temporal_stack([s0, s1], [c0, c1], comp_target, "quality_weighted_mean")
