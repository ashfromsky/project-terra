"""Theil-Sen slope estimator over exact elapsed UTC timestamps with Gilbert CIs."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.domain.models.temporal import JULIAN_YEAR_DAYS, SECONDS_PER_DAY

SECONDS_PER_YEAR = JULIAN_YEAR_DAYS * SECONDS_PER_DAY


@dataclass(frozen=True, slots=True)
class SensSlopeEstimate:
    """Intermediate numerical outcome returned by compute_sens_slope."""

    slope: float
    intercept: float
    ci_low: float | None
    ci_high: float | None
    unit: str
    pair_count: int
    all_slopes: NDArray[np.float64]


def elapsed_time_coordinate(
    timestamps: list[datetime],
    time_unit: str = "year",
) -> NDArray[np.float64]:
    """Convert ordered UTC timestamps into elapsed numeric coordinate in target time_unit."""
    if not timestamps:
        return np.array([], dtype=np.float64)
    t0 = timestamps[0]
    seconds = np.array([(ts - t0).total_seconds() for ts in timestamps], dtype=np.float64)
    norm_unit = time_unit.strip().lower()
    if norm_unit == "year":
        return seconds / SECONDS_PER_YEAR
    if norm_unit == "day":
        return seconds / SECONDS_PER_DAY
    if norm_unit == "hour":
        return seconds / 3600.0
    return np.arange(len(timestamps), dtype=np.float64)


def mk_tie_corrected_variance(values: NDArray[np.float64]) -> float:
    """Exact tie-adjusted Mann-Kendall variance Var(S) for finite array values."""
    n = int(values.size)
    if n < 2:
        return 0.0
    base = float(n * (n - 1) * (2 * n + 5))
    _, counts = np.unique(values, return_counts=True)
    tie_corr = sum(float(t * (t - 1) * (2 * t + 5)) for t in counts if t > 1)
    return max((base - tie_corr) / 18.0, 0.0)


def compute_sens_slope(
    timestamps: list[datetime],
    values: NDArray[np.float64] | list[float | None],
    *,
    unit_label: str = "units",
    time_unit: str = "year",
    alpha: float = 0.05,
    var_s_override: float | None = None,
) -> SensSlopeEstimate:
    """Compute median pairwise Theil-Sen slope ignoring NaNs and duplicate timestamps."""
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    x_full = elapsed_time_coordinate(timestamps, time_unit=time_unit)
    valid_mask = np.isfinite(arr)
    x = x_full[valid_mask]
    y = arr[valid_mask]
    n = int(y.size)

    slope_unit = f"{unit_label}/{time_unit}"
    if n < 2:
        return SensSlopeEstimate(
            slope=float("nan"),
            intercept=float("nan"),
            ci_low=None,
            ci_high=None,
            unit=slope_unit,
            pair_count=0,
            all_slopes=np.array([], dtype=np.float64),
        )

    slopes_list: list[float] = []
    for i in range(n - 1):
        dt = x[i + 1 :] - x[i]
        dy = y[i + 1 :] - y[i]
        non_zero_dt = dt > 1e-12
        if np.any(non_zero_dt):
            slopes_list.extend((dy[non_zero_dt] / dt[non_zero_dt]).tolist())

    if not slopes_list:
        return SensSlopeEstimate(
            slope=float("nan"),
            intercept=float("nan"),
            ci_low=None,
            ci_high=None,
            unit=slope_unit,
            pair_count=0,
            all_slopes=np.array([], dtype=np.float64),
        )

    slopes_arr = np.sort(np.asarray(slopes_list, dtype=np.float64))
    slope = float(np.median(slopes_arr))
    intercept = float(np.median(y - slope * x))

    n_pairs = int(slopes_arr.size)
    var_s = var_s_override if var_s_override is not None else mk_tie_corrected_variance(y)

    ci_low: float | None = None
    ci_high: float | None = None
    if n_pairs >= 4 and var_s > 0.0:
        z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
        c_alpha = z_alpha * float(np.sqrt(var_s))
        m1 = 0.5 * (float(n_pairs) - c_alpha)
        m2 = 0.5 * (float(n_pairs) + c_alpha) + 1.0
        idx_low = int(np.clip(np.floor(m1) - 1, 0, n_pairs - 1))
        idx_high = int(np.clip(np.ceil(m2) - 1, 0, n_pairs - 1))
        ci_low = float(slopes_arr[idx_low])
        ci_high = float(slopes_arr[idx_high])

    return SensSlopeEstimate(
        slope=slope,
        intercept=intercept,
        ci_low=ci_low,
        ci_high=ci_high,
        unit=slope_unit,
        pair_count=n_pairs,
        all_slopes=slopes_arr,
    )
