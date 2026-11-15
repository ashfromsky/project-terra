"""Seasonal reference climatology computation with baseline leakage prevention."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import BaselineType, SeasonalGrouping
from terra_scientific.domain.exceptions import InsufficientDataError
from terra_scientific.domain.models.request import BaselineConfig
from terra_scientific.domain.models.result import BaselineClimatologyResult, ClimatologyBin
from terra_scientific.domain.models.temporal import ensure_utc
from terra_scientific.temporal.seasonal import seasonal_group_keys

MAD_NORMAL_CONSTANT = 1.4826


def select_reference_mask(
    timestamps: list[datetime],
    config: BaselineConfig,
    *,
    assessment_start: datetime | None = None,
    assessment_end: datetime | None = None,
) -> tuple[list[bool], list[str], datetime, datetime]:
    """Build boolean mask selecting eligible baseline timestamps without data leakage."""
    norm_ts = [ensure_utc(ts) for ts in timestamps]
    if not norm_ts:
        raise InsufficientDataError("Cannot compute climatology on empty timestamp list")

    ref_start = config.start if config.start is not None else norm_ts[0]
    ref_end = config.end if config.end is not None else norm_ts[-1]
    warnings: list[str] = []

    if config.baseline_type == BaselineType.FIXED_REFERENCE:
        mask = [ref_start <= ts <= ref_end for ts in norm_ts]
    elif config.baseline_type == BaselineType.OUT_OF_SAMPLE:
        mask = [
            not (
                assessment_start is not None
                and assessment_end is not None
                and assessment_start <= ts <= assessment_end
            )
            for ts in norm_ts
        ]
        if any(mask):
            selected_ts = [ts for ts, m in zip(norm_ts, mask, strict=True) if m]
            ref_start, ref_end = selected_ts[0], selected_ts[-1]
    elif config.baseline_type == BaselineType.CROSS_VALIDATED:
        mask = [True for _ in norm_ts]
        warnings.append(
            "Cross-validated baseline uses leave-one-year-out reference stratification "
            "at anomaly evaluation."
        )
    else:
        mask = [True for _ in norm_ts]
        warnings.append(
            "Explicit full-period baseline includes assessment period inside reference statistics."
        )

    if (
        config.baseline_type == BaselineType.FIXED_REFERENCE
        and config.exclude_assessment_overlap
        and assessment_start is not None
        and assessment_end is not None
    ):
        a_start = ensure_utc(assessment_start)
        a_end = ensure_utc(assessment_end)
        overlapped = False
        new_mask: list[bool] = []
        for ts, keep in zip(norm_ts, mask, strict=True):
            if keep and a_start <= ts <= a_end:
                new_mask.append(False)
                overlapped = True
            else:
                new_mask.append(keep)
        if overlapped:
            mask = new_mask
            warnings.append(
                "Excluded overlapping assessment window observations from fixed reference "
                "baseline to prevent data leakage."
            )

    return mask, warnings, ref_start, ref_end


def compute_climatology(
    timestamps: list[datetime],
    values: Sequence[float | None] | NDArray[np.float64],
    config: BaselineConfig,
    *,
    variable_name: str,
    units: str,
    dataset_id: str = "",
    composite_days: int | None = None,
    assessment_start: datetime | None = None,
    assessment_end: datetime | None = None,
    raise_on_insufficient: bool = False,
) -> BaselineClimatologyResult:
    """Compute parametric and robust seasonal climatology bins for reference observations."""
    mask, warnings, ref_start, ref_end = select_reference_mask(
        timestamps,
        config,
        assessment_start=assessment_start,
        assessment_end=assessment_end,
    )

    group_keys, group_labels = seasonal_group_keys(
        timestamps, config.seasonal_grouping, composite_days=composite_days
    )
    arr = np.array(
        [np.nan if v is None else float(v) for v in values],
        dtype=np.float64,
    )

    bin_vals: dict[int, list[float]] = defaultdict(list)
    bin_labels: dict[int, str] = {}
    ref_years: set[int] = set()

    for ts, gkey, glabel, val, keep in zip(
        timestamps, group_keys, group_labels, arr, mask, strict=True
    ):
        bin_labels.setdefault(gkey, glabel)
        if keep and np.isfinite(val):
            bin_vals[gkey].append(float(val))
            ref_years.add(ts.year)

    bins: list[ClimatologyBin] = []
    insufficient_bins: list[str] = []

    for gkey in sorted(bin_labels):
        samples = np.asarray(bin_vals.get(gkey, []), dtype=np.float64)
        cnt = int(samples.size)
        if cnt == 0:
            bins.append(
                ClimatologyBin(
                    bin_key=gkey,
                    bin_label=bin_labels[gkey],
                    sample_count=0,
                    mean=None,
                    median=None,
                    std=None,
                    mad=None,
                    iqr=None,
                    q10=None,
                    q90=None,
                )
            )
            insufficient_bins.append(bin_labels[gkey])
            continue

        if cnt < config.min_samples_per_bin:
            insufficient_bins.append(bin_labels[gkey])

        mean_v = float(np.mean(samples))
        med_v = float(np.median(samples))
        std_v = float(np.std(samples, ddof=1)) if cnt > 1 else None
        raw_mad = float(np.median(np.abs(samples - med_v)))
        mad_v = MAD_NORMAL_CONSTANT * raw_mad
        q10, q25, q75, q90 = np.percentile(samples, [10.0, 25.0, 75.0, 90.0])

        bins.append(
            ClimatologyBin(
                bin_key=gkey,
                bin_label=bin_labels[gkey],
                sample_count=cnt,
                mean=mean_v,
                median=med_v,
                std=std_v,
                mad=mad_v,
                iqr=float(q75 - q25),
                q10=float(q10),
                q90=float(q90),
            )
        )

    years_ok = len(ref_years) >= config.min_years_required
    if not years_ok:
        warnings.append(
            f"Reference period spans {len(ref_years)} valid years, fewer than required "
            f"{config.min_years_required}."
        )
    if insufficient_bins:
        warnings.append(
            f"Insufficient baseline samples (< {config.min_samples_per_bin}) in seasonal bins: "
            f"{', '.join(insufficient_bins[:6])}"
        )

    sufficient = years_ok and len(insufficient_bins) == 0 and len(bins) > 0
    if not sufficient and raise_on_insufficient:
        raise InsufficientDataError(
            "Baseline reference period does not meet minimum years or sample count thresholds.",
            details={
                "valid_years": len(ref_years),
                "min_years_required": config.min_years_required,
                "insufficient_bins": insufficient_bins,
            },
        )

    return BaselineClimatologyResult(
        dataset_id=dataset_id,
        variable_name=variable_name,
        units=units,
        baseline_type=config.baseline_type.value,
        reference_start=ref_start,
        reference_end=ref_end,
        seasonal_grouping=SeasonalGrouping(config.seasonal_grouping).value,
        bins=bins,
        sufficient=sufficient,
        warnings=warnings,
    )
