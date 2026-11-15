"""Benjamini-Hochberg false discovery rate (FDR) multiple-testing adjustment."""

import numpy as np
from numpy.typing import NDArray


def benjamini_hochberg_fdr(
    p_values: NDArray[np.float64],
    *,
    alpha: float = 0.05,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Apply Benjamini-Hochberg step-up adjustment preserving NaN mask shape."""
    shape = p_values.shape
    flat_p = np.asarray(p_values, dtype=np.float64).ravel()
    q_out = np.full(flat_p.shape, np.nan, dtype=np.float64)
    sig_out = np.zeros(flat_p.shape, dtype=bool)

    valid_idx = np.flatnonzero(np.isfinite(flat_p))
    m = int(valid_idx.size)
    if m == 0:
        return q_out.reshape(shape), sig_out.reshape(shape)

    valid_p = np.clip(flat_p[valid_idx], 0.0, 1.0)
    order = np.argsort(valid_p, kind="mergesort")
    sorted_p = valid_p[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    raw_q = sorted_p * (float(m) / ranks)
    monotone_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    monotone_q = np.clip(monotone_q, 0.0, 1.0)

    unsorted_q = np.empty(m, dtype=np.float64)
    unsorted_q[order] = monotone_q
    q_out[valid_idx] = unsorted_q
    sig_out[valid_idx] = unsorted_q <= alpha
    return q_out.reshape(shape), sig_out.reshape(shape)
