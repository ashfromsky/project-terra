"""Hirsch-Slack Seasonal Mann-Kendall and within-season Theil-Sen slope estimator."""

from collections import defaultdict
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

from terra_scientific.domain.enums import SeasonalGrouping, TrendDirection
from terra_scientific.domain.models.request import TrendConfig
from terra_scientific.domain.models.result import SeasonalGroupTrend, SeasonalTrendResult
from terra_scientific.temporal.seasonal import seasonal_group_keys
from terra_scientific.trends.mann_kendall import _mk_s_and_ties
from terra_scientific.trends.sens_slope import compute_sens_slope


def compute_seasonal_mann_kendall(
    timestamps: list[datetime],
    values: NDArray[np.float64] | list[float | None],
    config: TrendConfig | None = None,
    *,
    dataset_id: str = "",
    variable_name: str = "variable",
    units: str = "units",
    composite_days: int | None = None,
) -> SeasonalTrendResult:
    """Compute Seasonal Mann-Kendall and pooled within-season Sen slope."""
    cfg = config or TrendConfig()
    arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    gkeys, glabels = seasonal_group_keys(
        timestamps, cfg.seasonal_grouping, composite_days=composite_days
    )

    warnings: list[str] = []
    if composite_days == 16 and cfg.seasonal_grouping == SeasonalGrouping.CALENDAR_MONTH:
        warnings.append(
            "Applying calendar-month grouping directly to un-aggregated 16-day composites; "
            "consider COMPOSITE_DOY_BIN or monthly aggregation first."
        )

    by_season: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    label_map: dict[int, str] = {}
    for ts, val, gkey, glabel in zip(timestamps, arr, gkeys, glabels, strict=True):
        label_map.setdefault(gkey, glabel)
        if np.isfinite(val):
            by_season[gkey].append((ts, float(val)))

    season_results: list[SeasonalGroupTrend] = []
    total_s = 0.0
    total_var_s = 0.0
    pooled_slopes: list[float] = []

    for gkey in sorted(by_season):
        pairs = sorted(by_season[gkey], key=lambda item: item[0])
        if len(pairs) < 2:
            continue
        s_ts = [p[0] for p in pairs]
        s_y = np.asarray([p[1] for p in pairs], dtype=np.float64)
        s_g, var_g, _ = _mk_s_and_ties(s_y)
        sens_g = compute_sens_slope(
            s_ts, s_y, unit_label=units, time_unit=cfg.slope_time_unit, alpha=cfg.alpha
        )
        total_s += s_g
        total_var_s += var_g
        if sens_g.all_slopes.size > 0:
            pooled_slopes.extend(sens_g.all_slopes.tolist())
        season_results.append(
            SeasonalGroupTrend(
                season_key=gkey,
                season_label=label_map[gkey],
                sample_count=len(pairs),
                s_statistic=float(s_g),
                var_s=float(var_g),
                sens_slope=float(sens_g.slope) if np.isfinite(sens_g.slope) else None,
            )
        )

    valid_total = sum(item.sample_count for item in season_results)
    if valid_total < cfg.min_samples or not season_results:
        return SeasonalTrendResult(
            dataset_id=dataset_id,
            variable_name=variable_name,
            grouping_mode=cfg.seasonal_grouping.value,
            overall_direction=TrendDirection.INSUFFICIENT_DATA,
            slope_unit=f"{units}/{cfg.slope_time_unit}",
            season_results=season_results,
            warnings=[
                *warnings,
                f"Insufficient seasonal observations ({valid_total}) for Seasonal MK.",
            ],
        )

    z_stat = 0.0
    if total_var_s > 0.0:
        if total_s > 0:
            z_stat = (total_s - 1.0) / float(np.sqrt(total_var_s))
        elif total_s < 0:
            z_stat = (total_s + 1.0) / float(np.sqrt(total_var_s))
        p_val = float(2.0 * norm.sf(abs(z_stat)))
    else:
        p_val = 1.0

    if p_val < cfg.alpha:
        direction = TrendDirection.INCREASING if total_s > 0 else TrendDirection.DECREASING
    else:
        direction = TrendDirection.NO_TREND

    global_slope = float(np.median(pooled_slopes)) if pooled_slopes else None

    return SeasonalTrendResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        grouping_mode=cfg.seasonal_grouping.value,
        overall_direction=direction,
        total_s=float(total_s),
        total_var_s=float(total_var_s),
        z_statistic=float(z_stat),
        p_value=float(p_val),
        seasonal_sens_slope=global_slope,
        slope_unit=f"{units}/{cfg.slope_time_unit}",
        season_results=season_results,
        warnings=warnings,
    )
