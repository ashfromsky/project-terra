"""Source-aware temporal unit conversions and interval-preserving aggregation."""

from collections import defaultdict
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import (
    AggregationOperator,
    DataSourceId,
    TemporalCadence,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import TemporalAlignmentError
from terra_scientific.domain.models.dataset import VariableMetadata
from terra_scientific.domain.models.result import TemporalSeriesResult


def kelvin_to_celsius(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert temperature array from Kelvin to Celsius while preserving NaN."""
    return np.asarray(values - 273.15, dtype=np.float64)


def integrate_imerg_half_hourly_day(
    rate_values_mm_hr: NDArray[np.float64],
    *,
    expected_intervals: int = 48,
    interval_hours: float = 0.5,
    min_coverage: float = 0.7,
) -> tuple[float | None, int, int, float]:
    """Convert half-hourly IMERG rates (mm/hr) to daily depth (mm) respecting missingness."""
    valid_mask = np.isfinite(rate_values_mm_hr)
    valid_count = int(np.sum(valid_mask))
    exp_count = max(expected_intervals, int(rate_values_mm_hr.size), 1)
    coverage = valid_count / exp_count
    if valid_count == 0 or coverage < min_coverage:
        return None, valid_count, exp_count, coverage
    depth_mm = float(np.sum(rate_values_mm_hr[valid_mask] * interval_hours))
    return depth_mm, valid_count, exp_count, coverage


def _period_key_and_timestamp(
    ts: datetime,
    target_cadence: TemporalCadence,
) -> tuple[tuple[int, int, int], datetime]:
    ts_utc = ts.astimezone(UTC)
    if target_cadence == TemporalCadence.DAILY:
        return (ts_utc.year, ts_utc.month, ts_utc.day), datetime(
            ts_utc.year, ts_utc.month, ts_utc.day, tzinfo=UTC
        )
    if target_cadence == TemporalCadence.MONTHLY:
        return (ts_utc.year, ts_utc.month, 1), datetime(ts_utc.year, ts_utc.month, 1, tzinfo=UTC)
    if target_cadence == TemporalCadence.SEASONAL:
        q = 1 + (ts_utc.month - 1) // 3
        first_month = (q - 1) * 3 + 1
        return (ts_utc.year, q, 1), datetime(ts_utc.year, first_month, 1, tzinfo=UTC)
    if target_cadence == TemporalCadence.ANNUAL:
        return (ts_utc.year, 1, 1), datetime(ts_utc.year, 1, 1, tzinfo=UTC)
    return (ts_utc.year, ts_utc.month, ts_utc.day), ts_utc


def _reduce_period(valid_vals: NDArray[np.float64], operator: AggregationOperator) -> float:
    if operator == AggregationOperator.MEAN:
        return float(np.mean(valid_vals))
    if operator == AggregationOperator.MEDIAN:
        return float(np.median(valid_vals))
    if operator == AggregationOperator.SUM:
        return float(np.sum(valid_vals))
    if operator == AggregationOperator.MIN:
        return float(np.min(valid_vals))
    if operator == AggregationOperator.MAX:
        return float(np.max(valid_vals))
    return float(valid_vals.size)


def aggregate_temporal_series(
    values: NDArray[np.float64],
    timestamps: list[datetime],
    metadata: VariableMetadata,
    target_cadence: TemporalCadence,
    operator: AggregationOperator,
    *,
    source_id: DataSourceId = DataSourceId.CUSTOM,
    dataset_id: str = "",
    expected_steps_per_period: int | None = None,
    min_coverage: float = 0.7,
) -> TemporalSeriesResult:
    """Aggregate screened time series while enforcing physical & rate-vs-depth rules."""
    if len(timestamps) != values.size:
        raise TemporalAlignmentError("timestamps length must equal values array length")

    work_vals = np.array(values, dtype=np.float64, copy=True)
    out_units = metadata.units
    warnings: list[str] = []

    is_imerg_rate = (
        source_id == DataSourceId.GPM_IMERG
        and "hr" in metadata.units.lower()
        and operator == AggregationOperator.SUM
    )
    if is_imerg_rate:
        work_vals = work_vals * 0.5
        out_units = "mm"
    elif (
        operator == AggregationOperator.SUM
        and metadata.semantic_kind == VariableSemanticKind.CONTINUOUS_INTENSIVE
        and not is_imerg_rate
    ):
        raise TemporalAlignmentError(
            f"Cannot sum intensive variable '{metadata.name}' ({metadata.units}) across time; "
            "use mean, median, min, or max instead."
        )

    if target_cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}:
        return TemporalSeriesResult(
            dataset_id=dataset_id,
            variable_name=metadata.name,
            units=out_units,
            cadence=target_cadence,
            aggregation_operator=operator,
            timestamps=list(timestamps),
            values=[None if np.isnan(v) else float(v) for v in work_vals],
            expected_subintervals=[1] * len(timestamps),
            valid_subintervals=[0 if np.isnan(v) else 1 for v in work_vals],
            coverage_fractions=[0.0 if np.isnan(v) else 1.0 for v in work_vals],
            warnings=warnings,
        )

    buckets: dict[tuple[int, int, int], list[float]] = defaultdict(list)
    bucket_ts: dict[tuple[int, int, int], datetime] = {}
    for ts, val in zip(timestamps, work_vals, strict=True):
        pkey, p_ts = _period_key_and_timestamp(ts, target_cadence)
        buckets[pkey].append(float(val))
        bucket_ts.setdefault(pkey, p_ts)

    out_timestamps: list[datetime] = []
    out_values: list[float | None] = []
    out_expected: list[int] = []
    out_valid: list[int] = []
    out_cov: list[float] = []

    for pkey in sorted(buckets):
        arr = np.asarray(buckets[pkey], dtype=np.float64)
        valid = arr[np.isfinite(arr)]
        exp_n = (
            expected_steps_per_period if expected_steps_per_period is not None else int(arr.size)
        )
        exp_n = max(exp_n, int(arr.size), 1)
        val_n = int(valid.size)
        cov = val_n / exp_n
        out_timestamps.append(bucket_ts[pkey])
        out_expected.append(exp_n)
        out_valid.append(val_n)
        out_cov.append(cov)
        if val_n == 0 or cov < min_coverage:
            out_values.append(None)
        else:
            out_values.append(_reduce_period(valid, operator))

    return TemporalSeriesResult(
        dataset_id=dataset_id,
        variable_name=metadata.name,
        units=out_units,
        cadence=target_cadence,
        aggregation_operator=operator,
        timestamps=out_timestamps,
        values=out_values,
        expected_subintervals=out_expected,
        valid_subintervals=out_valid,
        coverage_fractions=out_cov,
        warnings=warnings,
    )
