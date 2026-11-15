"""Seasonal grouping utilities preserving calendar-month vs composite-DOY semantics."""

from datetime import datetime

from terra_scientific.domain.enums import SeasonalGrouping


def seasonal_group_keys(
    timestamps: list[datetime],
    grouping: SeasonalGrouping = SeasonalGrouping.CALENDAR_MONTH,
    composite_days: int | None = None,
) -> tuple[list[int], list[str]]:
    """Assign each timestamp an integer seasonal bin and human-readable label."""
    if grouping == SeasonalGrouping.CALENDAR_MONTH:
        keys = [ts.month for ts in timestamps]
        labels = [f"Month_{ts.month:02d}" for ts in timestamps]
        return keys, labels

    if grouping == SeasonalGrouping.QUARTERLY:
        keys = [1 + (ts.month - 1) // 3 for ts in timestamps]
        labels = [f"Q{k}" for k in keys]
        return keys, labels

    if grouping == SeasonalGrouping.COMPOSITE_DOY_BIN:
        step = composite_days if composite_days is not None and composite_days > 0 else 16
        keys = [1 + (ts.timetuple().tm_yday - 1) // step for ts in timestamps]
        labels = [f"DOY_bin_{k:02d}" for k in keys]
        return keys, labels

    keys = [ts.month for ts in timestamps]
    labels = [f"Season_{k:02d}" for k in keys]
    return keys, labels
