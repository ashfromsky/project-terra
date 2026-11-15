"""Scientific validation tests comparing Mann-Kendall & Sen's slope to exact benchmarks."""

from datetime import UTC, datetime

import numpy as np
import pytest

from terra_scientific.domain.enums import TrendDirection
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.trends.mann_kendall import compute_mann_kendall


def test_mann_kendall_matches_tie_corrected_variance_and_gilbert_benchmark() -> None:
    # Known sequence with ties: [1, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8, 9]
    # n = 12 => n(n-1)(2n+5) = 12 * 11 * 29 = 3828
    # tie group 2 (t=2): 2*1*(9) = 18; tie group 4 (t=3): 3*2*(11) = 66
    # exact Var(S) = (3828 - 18 - 66) / 18 = 3744 / 18 = 208.0
    # S: 66 pairs minus (1 tie + 3 ties) = 62 -> Z_c = (62 - 1)/sqrt(208) = 61 / 14.422205 = 4.22959
    vals = np.array([1, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8, 9], dtype=np.float64)
    ts = [datetime(2000 + i, 1, 1, tzinfo=UTC) for i in range(12)]
    res = compute_mann_kendall(ts, vals, TrendConfig(min_samples=6))
    assert res.s_statistic == pytest.approx(62.0)
    assert res.var_s == pytest.approx(208.0)
    assert res.z_statistic == pytest.approx(61.0 / np.sqrt(208.0), rel=1e-5)
    assert res.direction == TrendDirection.INCREASING


def test_exact_permutation_null_distribution_p_values_for_n5() -> None:
    # For n=5 without ties (120 permutations), max S = 10 -> two-sided exact p = 2/120 = 1/60
    ts5 = [datetime(2020 + i, 1, 1, tzinfo=UTC) for i in range(5)]
    res5 = compute_mann_kendall(
        ts5, np.array([10.0, 20.0, 30.0, 40.0, 50.0]), TrendConfig(min_samples=4)
    )
    assert res5.s_statistic == pytest.approx(10.0)
    assert res5.p_value == pytest.approx(2.0 / 120.0, abs=1e-8)
    assert res5.direction == TrendDirection.INCREASING
