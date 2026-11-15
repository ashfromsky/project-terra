"""Scientific validation benchmarks for Moran's I, FDR, and partial correlation."""

import numpy as np
import pytest

from terra_scientific.cross_variable.analysis import compute_partial_correlation
from terra_scientific.spatial.autocorrelation import compute_morans_i_and_hotspots
from terra_scientific.spatial.fdr import benjamini_hochberg_fdr


def test_benjamini_hochberg_exact_reference_calculation() -> None:
    # Sorted p = [0.001, 0.008, 0.039, 0.041, 0.06], m = 5.
    # With m=5: raw p*(5/k) = [0.005, 0.020, 0.065, 0.05125, 0.06]
    # Backwards step-up cummin forces q[2] = min(0.065, 0.05125) = 0.05125!
    pvals = np.array([0.039, 0.001, 0.06, 0.041, 0.008], dtype=np.float64)
    qvals, sig = benjamini_hochberg_fdr(pvals, alpha=0.05)
    assert qvals[1] == pytest.approx(0.005)
    assert qvals[4] == pytest.approx(0.020)
    assert qvals[0] == pytest.approx(0.05125)
    assert qvals[3] == pytest.approx(0.05125)
    assert not sig[0]
    assert sig[1] and sig[4]


def test_checkerboard_has_negative_morans_i_and_spurious_correlation_eliminated_by_partial() -> (
    None
):
    # Rook contiguity across 6x6 checkerboard produces strictly negative spatial autocorrelation.
    checker = np.fromfunction(lambda r, c: ((r + c) % 2).astype(np.float64), (6, 6))
    ac = compute_morans_i_and_hotspots(checker, permutations=0, connectivity="rook")
    assert ac.morans_i is not None and ac.morans_i < -0.9

    # Spurious correlation caused solely by shared Z vanishes after partialing out Z
    rng = np.random.default_rng(100)
    z = np.linspace(-3.0, 3.0, 80)
    x = 3.0 * z + rng.normal(scale=0.1, size=80)
    y = -2.0 * z + rng.normal(scale=0.1, size=80)
    marginal_r = float(np.corrcoef(x, y)[0, 1])
    partial_r, partial_p = compute_partial_correlation(y, x, z[:, None])
    assert marginal_r < -0.95
    assert abs(partial_r) < 0.25
    assert partial_p > 0.05
