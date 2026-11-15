"""Explicit, opt-in internal temporal gap interpolation with synthetic provenance."""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.exceptions import MethodConfigurationError, TemporalAlignmentError


def interpolate_gaps_explicit(
    timestamps: list[datetime],
    values: NDArray[np.float64],
    *,
    method: str = "linear",
    max_gap_steps: int = 2,
) -> tuple[NDArray[np.float64], list[int], str]:
    """Fill short internal NaN gaps over elapsed seconds without edge extrapolation."""
    if method != "linear":
        raise MethodConfigurationError(f"Unsupported interpolation method: {method!r}")
    if len(timestamps) != values.size:
        raise TemporalAlignmentError("timestamps length must equal values array length")

    out = np.array(values, dtype=np.float64, copy=True)
    if out.size < 3:
        return out, [], "no interpolation possible (< 3 steps)"

    epoch_sec = np.array([ts.timestamp() for ts in timestamps], dtype=np.float64)
    valid_idx = np.flatnonzero(np.isfinite(out))
    if valid_idx.size < 2:
        return out, [], "insufficient valid anchors for interpolation"

    interpolated_indices: list[int] = []
    first_valid, last_valid = int(valid_idx[0]), int(valid_idx[-1])

    idx = first_valid + 1
    while idx < last_valid:
        if np.isfinite(out[idx]):
            idx += 1
            continue
        gap_start = idx
        while idx < last_valid and not np.isfinite(out[idx]):
            idx += 1
        gap_len = idx - gap_start
        if gap_len <= max_gap_steps:
            left = gap_start - 1
            right = idx
            t_left, t_right = epoch_sec[left], epoch_sec[right]
            v_left, v_right = out[left], out[right]
            dt_total = t_right - t_left
            for g in range(gap_start, idx):
                weight = (epoch_sec[g] - t_left) / dt_total if dt_total > 0 else 0.5
                out[g] = v_left + weight * (v_right - v_left)
                interpolated_indices.append(g)

    note = (
        f"Explicit linear internal gap interpolation applied (max_gap_steps={max_gap_steps}); "
        f"filled {len(interpolated_indices)} gaps without edge extrapolation."
    )
    return out, interpolated_indices, note
