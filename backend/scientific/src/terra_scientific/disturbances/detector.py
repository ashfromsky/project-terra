"""Pettitt change-point test and candidate anomaly disturbance run detection."""

from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata

from terra_scientific.anomalies.detector import _find_persistent_runs
from terra_scientific.domain.models.request import AnomalyConfig, DisturbanceConfig
from terra_scientific.domain.models.result import ChangePointEntry, DisturbanceResult


def _pettitt_single_split(
    y: NDArray[np.float64],
) -> tuple[int, float, float] | None:
    """Return (split_offset, K_T, approx_p) partitioning y into y[:split] and y[split:]."""
    n = int(y.size)
    if n < 6:
        return None
    ranks = rankdata(y, method="average")
    cum_ranks = np.cumsum(ranks[:-1])
    t_vec = np.arange(1, n, dtype=np.float64)
    u_vec = t_vec * float(n + 1) - 2.0 * cum_ranks
    abs_u = np.abs(u_vec)
    best_t_minus_1 = int(np.argmax(abs_u))
    k_t = float(abs_u[best_t_minus_1])
    p_val = float(min(1.0, 2.0 * np.exp((-6.0 * (k_t**2)) / float(n**3 + n**2))))
    return best_t_minus_1 + 1, k_t, p_val


def _recursive_pettitt(
    timestamps: list[datetime],
    values: NDArray[np.float64],
    orig_indices: NDArray[np.int64],
    start: int,
    end: int,
    *,
    alpha: float,
    min_seg_len: int,
    out: list[ChangePointEntry],
) -> None:
    seg_len = end - start
    if seg_len < max(min_seg_len * 2, 6):
        return
    seg_vals = values[start:end]
    res = _pettitt_single_split(seg_vals)
    if res is None:
        return
    offset, k_t, p_val = res
    if offset < min_seg_len or (seg_len - offset) < min_seg_len:
        return
    if p_val > alpha:
        return

    before_mean = float(np.mean(seg_vals[:offset]))
    after_mean = float(np.mean(seg_vals[offset:]))
    global_pos = int(orig_indices[start + offset])
    out.append(
        ChangePointEntry(
            method="pettitt_1979",
            timestamp=timestamps[global_pos],
            index=global_pos,
            statistic=k_t,
            p_value=p_val,
            mean_before=before_mean,
            mean_after=after_mean,
            shift_magnitude=after_mean - before_mean,
        )
    )
    _recursive_pettitt(
        timestamps,
        values,
        orig_indices,
        start,
        start + offset,
        alpha=alpha,
        min_seg_len=min_seg_len,
        out=out,
    )
    _recursive_pettitt(
        timestamps,
        values,
        orig_indices,
        start + offset,
        end,
        alpha=alpha,
        min_seg_len=min_seg_len,
        out=out,
    )


def detect_disturbances(
    timestamps: list[datetime],
    values: NDArray[np.float64] | list[float | None],
    zscores: NDArray[np.float64] | list[float | None] | None = None,
    config: DisturbanceConfig | None = None,
    *,
    dataset_id: str = "",
    variable_name: str = "variable",
) -> DisturbanceResult:
    """Identify statistically significant change points and persistent anomaly episodes."""
    cfg = config or DisturbanceConfig()
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    valid_mask = np.isfinite(arr)
    valid_idx = np.flatnonzero(valid_mask)
    valid_vals = arr[valid_mask]

    warnings: list[str] = []
    change_points: list[ChangePointEntry] = []
    if valid_vals.size < max(cfg.min_segment_length * 2, 6):
        warnings.append("Series too short for Pettitt change-point segmentation.")
    else:
        _recursive_pettitt(
            timestamps,
            valid_vals,
            valid_idx,
            0,
            int(valid_vals.size),
            alpha=cfg.alpha,
            min_seg_len=cfg.min_segment_length,
            out=change_points,
        )
        change_points.sort(key=lambda cp: cp.index)

    runs = []
    if zscores is not None:
        z_list: list[float | None] = [
            None if z is None or not np.isfinite(float(z)) else float(z) for z in zscores
        ]
        raw_diffs: list[float | None] = [None if not np.isfinite(v) else float(v) for v in arr]
        anom_cfg = AnomalyConfig(
            zscore_threshold=min(abs(cfg.negative_z_threshold), abs(cfg.positive_z_threshold)),
            min_persistence_steps=cfg.min_event_steps,
        )
        runs = _find_persistent_runs(timestamps, z_list, raw_diffs, anom_cfg)

    return DisturbanceResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        change_points=change_points,
        candidate_disturbance_runs=runs,
        warnings=warnings,
    )
