"""Adaptive readiness evaluator checking datasets and methodologies against scientific criteria."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import numpy as np

from terra_scientific.baselines.climatology import select_reference_mask
from terra_scientific.domain.enums import (
    AggregationOperator,
    BaselineType,
    DataSourceId,
    PriorityTier,
    SeasonalGrouping,
    TemporalCadence,
    VariableSemanticKind,
)
from terra_scientific.domain.exceptions import ScientificCoreError
from terra_scientific.domain.models.dataset import ScientificDataset, ScientificGridStack
from terra_scientific.domain.models.quality import QualitySummary
from terra_scientific.domain.models.readiness import (
    CriterionStatus,
    DatasetReadinessProfile,
    MetricAvailability,
    ReadinessAssessmentReport,
    ReadinessCriterion,
    ReadinessLevel,
)
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.domain.models.result import TemporalSeriesResult
from terra_scientific.domain.models.temporal import ensure_utc
from terra_scientific.quality.validator import screen_dataset_variable, screen_grid_stack
from terra_scientific.readiness.specs import (
    get_source_readiness_profile,
    resolve_aggregation_min_coverage,
    resolve_baseline_requirements,
    resolve_qa_sufficiency_threshold,
    resolve_trend_requirements,
)
from terra_scientific.spatial.zonal import extract_area_weighted_series
from terra_scientific.temporal.aggregation import aggregate_temporal_series
from terra_scientific.temporal.seasonal import seasonal_group_keys


def _stage_enabled(request: AssessmentRequest, name: str) -> bool:
    return request.enabled_stages is None or name in request.enabled_stages


def _format_span(span_years: float) -> str:
    return f"{span_years:.2f} yr"


def _subtract_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year - years)
    except ValueError:
        return dt - timedelta(days=365 * years)


def _evaluate_variable_series(
    ds: ScientificDataset,
    var_name: str,
    request: AssessmentRequest,
    stacks: Mapping[str, ScientificGridStack],
    existing_quality: Mapping[str, QualitySummary] | None,
    existing_series: Mapping[str, TemporalSeriesResult] | None,
) -> tuple[QualitySummary | None, TemporalSeriesResult | None, list[str]]:
    key = f"{ds.dataset_id}:{var_name}"
    notes: list[str] = []
    min_cov, _ = resolve_aggregation_min_coverage(
        ds.source_id,
        ds.temporal_metadata.cadence,
        request.target_cadence,
        request.qa_level,
    )

    if existing_quality is not None and key in existing_quality:
        q_summary = existing_quality[key]
        if existing_series is not None and key in existing_series:
            return q_summary, existing_series[key], notes
        if not q_summary.passed_sufficiency:
            return q_summary, None, notes

    try:
        stack = stacks.get(key) or stacks.get(var_name)
        if ds.series.get(var_name) is not None:
            screened_1d, q_summary = screen_dataset_variable(
                ds,
                var_name,
                qa_level=request.qa_level,
                overpass_mode=request.smap_overpass_mode,
                allow_imerg_early_late=request.allow_imerg_early_late,
            )
            raw_ts = ds.series[var_name].timestamps
            var_meta = ds.series[var_name].metadata
        elif stack is not None:
            screened_stack, q_summary = screen_grid_stack(
                stack,
                qa_level=request.qa_level,
                allow_imerg_early_late=request.allow_imerg_early_late,
                run_type=ds.run_type,
            )
            raw_ts, screened_1d = extract_area_weighted_series(
                screened_stack, min_spatial_coverage=request.spatial.min_pixel_coverage
            )
            var_meta = screened_stack.variable
        else:
            notes.append(f"Variable '{key}' has no 1D series or 3D raster stack.")
            return None, None, notes

        op = request.aggregation_operator
        if ds.source_id == DataSourceId.GPM_IMERG and "hr" in var_meta.units.lower():
            op = AggregationOperator.SUM
        elif (
            op == AggregationOperator.SUM
            and var_meta.semantic_kind == VariableSemanticKind.CONTINUOUS_INTENSIVE
        ):
            op = AggregationOperator.MEAN

        temp_res = aggregate_temporal_series(
            values=screened_1d,
            timestamps=raw_ts,
            metadata=var_meta,
            target_cadence=request.target_cadence,
            operator=op,
            source_id=ds.source_id,
            dataset_id=ds.dataset_id,
            min_coverage=min_cov,
        )
        return q_summary, temp_res, notes
    except ScientificCoreError as exc:
        notes.append(f"{key}: {exc}")
        return None, None, notes


def evaluate_assessment_readiness(
    request: AssessmentRequest,
    *,
    datasets: Sequence[ScientificDataset],
    grid_stacks: Mapping[str, ScientificGridStack] | None = None,
    quality_reports: Mapping[str, QualitySummary] | None = None,
    temporal_series: Sequence[TemporalSeriesResult] | None = None,
) -> ReadinessAssessmentReport:
    """Evaluate source-specific and method-specific readiness before or after runs."""
    stacks = dict(grid_stacks or {})
    series_by_key = {f"{ts.dataset_id}:{ts.variable_name}": ts for ts in (temporal_series or [])}
    min_trend_req, rec_trend_steps, trend_rationale = resolve_trend_requirements(
        request.target_cadence, request.trend
    )
    min_years_req, min_bin_samples_req, base_rationale = resolve_baseline_requirements(
        baseline_type=request.baseline.baseline_type,
        seasonal_grouping=request.baseline.seasonal_grouping,
        explicit_min_years=request.baseline.min_years_required,
        explicit_min_samples_per_bin=request.baseline.min_samples_per_bin,
    )

    dataset_profiles: list[DatasetReadinessProfile] = []
    criteria: list[ReadinessCriterion] = []
    actions: list[str] = []

    def _add_action(text: str | None) -> None:
        if text and text not in actions:
            actions.append(text)

    if not datasets:
        criteria.append(
            ReadinessCriterion(
                criterion_id="datasets:presence",
                category="data_quality",
                stage_or_metric="All Stages",
                title="Input Datasets Available",
                required_summary=">= 1 quantitative dataset",
                actual_summary="0 datasets selected",
                required_value=1,
                actual_value=0,
                unit="datasets",
                status="failed",
                scientific_rationale=(
                    "Scientific calculations require at least one validated quantitative time "
                    "series or gridded raster stack."
                ),
                missing_gap="No datasets are attached to this assessment request.",
                remediation="Select or auto-provision at least one prepared dataset for your AOI.",
            )
        )
        _add_action("Auto-provision or select at least one prepared dataset covering your AOI.")
        return ReadinessAssessmentReport(
            overall_status="insufficient",
            summary="No quantitative datasets are attached.",
            datasets=[],
            criteria=criteria,
            metrics=[],
            recommended_actions=actions,
            suggested_window_start=_subtract_years(request.analysis_end, min_years_req),
            suggested_window_end=request.analysis_end,
        )

    evaluated_series: list[tuple[ScientificDataset, str, QualitySummary, TemporalSeriesResult]] = []
    suggested_starts: list[datetime] = []

    for ds in datasets:
        profile = get_source_readiness_profile(ds.source_id)
        min_qa_req, qa_rationale = resolve_qa_sufficiency_threshold(
            ds.source_id, ds.product, request.qa_level
        )
        min_agg_cov, _ = resolve_aggregation_min_coverage(
            ds.source_id, ds.temporal_metadata.cadence, request.target_cadence, request.qa_level
        )

        var_names = list(ds.series.keys()) or [
            v for v in ds.variables if f"{ds.dataset_id}:{v}" in stacks or v in stacks
        ]
        qa_layers_present = sorted(
            {k for ser in ds.series.values() for k in ser.qa_layers}
            | {k for st in stacks.values() if st.dataset_id == ds.dataset_id for k in st.qa_arrays}
        )
        has_stack = bool(
            ds.raster_refs or any(st.dataset_id == ds.dataset_id for st in stacks.values())
        )

        ds_valid_fracs: list[float] = []
        ds_raw_counts: list[int] = []
        ds_valid_counts: list[int] = []
        ds_notes: list[str] = []
        ds_spans: list[float] = []
        ds_ts_all: list[datetime] = []
        ds_any_sufficient = False
        ds_all_sufficient = bool(var_names)

        for var_name in var_names:
            q_sum, t_res, var_notes = _evaluate_variable_series(
                ds, var_name, request, stacks, quality_reports, series_by_key
            )
            ds_notes.extend(var_notes)
            if q_sum is None:
                ds_all_sufficient = False
                criteria.append(
                    ReadinessCriterion(
                        criterion_id=f"qa_validity:{ds.dataset_id}:{var_name}",
                        category="data_quality",
                        dataset_id=ds.dataset_id,
                        variable_name=var_name,
                        stage_or_metric="QA Screening & Temporal Extraction",
                        title=f"{var_name} QA & Input Policy ({ds.product})",
                        required_summary=(
                            f">= {min_qa_req:.0%} valid under {request.qa_level.value} QA"
                        ),
                        actual_summary="Rejected by source/QA input policy",
                        required_value=round(min_qa_req, 3),
                        actual_value=0.0,
                        unit="fraction",
                        status="failed",
                        scientific_rationale=qa_rationale,
                        missing_gap="; ".join(var_notes) or "Input failed source validation.",
                        remediation=(
                            "Verify source run type, SMAP overpass separation, "
                            "or ingest compliant data."
                        ),
                    )
                )
                _add_action(ds_notes[-1] if ds_notes else None)
                continue

            ds_valid_fracs.append(q_sum.valid_fraction)
            ds_raw_counts.append(q_sum.total_observations)
            ds_valid_counts.append(q_sum.valid_observations)
            qa_status: CriterionStatus = "passed" if q_sum.passed_sufficiency else "failed"
            if q_sum.passed_sufficiency:
                ds_any_sufficient = True
                if any("no qa flag layers" in w.lower() for w in q_sum.warnings):
                    qa_status = "warning"
            else:
                ds_all_sufficient = False

            qa_gap: str | None = None
            qa_rem: str | None = None
            if not q_sum.passed_sufficiency:
                qa_gap = (
                    f"Only {q_sum.valid_observations}/{q_sum.total_observations} steps "
                    f"({q_sum.valid_fraction:.1%}) passed QA/fill/range screening."
                )
                qa_rem = (
                    f"Expand window or re-ingest {ds.product} with QA layers; or switch QA "
                    "to permissive / use NASA POWER for continuous meteorology."
                )
                _add_action(qa_rem)
            elif qa_status == "warning":
                qa_gap = "Explicit QA flag layers missing; physical range & fill checks only."
                qa_rem = f"Re-ingest {ds.product} preserving official QA layers in GHS."

            criteria.append(
                ReadinessCriterion(
                    criterion_id=f"qa_validity:{ds.dataset_id}:{var_name}",
                    category="data_quality",
                    dataset_id=ds.dataset_id,
                    variable_name=var_name,
                    stage_or_metric="QA Screening",
                    title=f"{var_name} QA Validity ({ds.product})",
                    required_summary=f">= {min_qa_req:.0%} valid observations",
                    actual_summary=(
                        f"{q_sum.valid_observations}/{q_sum.total_observations} steps "
                        f"({q_sum.valid_fraction:.1%}, {q_sum.qa_policy_applied})"
                    ),
                    required_value=round(min_qa_req, 3),
                    actual_value=round(q_sum.valid_fraction, 3),
                    unit="fraction",
                    status=qa_status,
                    scientific_rationale=qa_rationale,
                    missing_gap=qa_gap,
                    remediation=qa_rem,
                )
            )

            if t_res is None:
                continue

            evaluated_series.append((ds, var_name, q_sum, t_res))
            valid_pairs = [
                (ensure_utc(ts), float(val))
                for ts, val in zip(t_res.timestamps, t_res.values, strict=True)
                if val is not None and np.isfinite(val)
            ]
            valid_ts = [pair[0] for pair in valid_pairs]
            ds_ts_all.extend(valid_ts)
            span_yr = (
                (max(valid_ts) - min(valid_ts)).total_seconds() / (365.25 * 86400.0)
                if len(valid_ts) >= 2
                else 0.0
            )
            ds_spans.append(span_yr)
            n_agg = len(valid_pairs)

            trend_ok = n_agg >= min_trend_req
            trend_status: CriterionStatus = (
                "failed" if not trend_ok else ("warning" if n_agg < rec_trend_steps else "passed")
            )
            trend_gap: str | None = None
            trend_rem: str | None = None
            if not trend_ok:
                deficit = min_trend_req - n_agg
                trend_gap = (
                    f"Missing {deficit} valid {request.target_cadence.value} step(s) for "
                    "Mann-Kendall."
                )
                trend_rem = (
                    f"Extend temporal coverage to accumulate >= {min_trend_req} valid "
                    f"{request.target_cadence.value} observations."
                )
                _add_action(trend_rem)
            elif n_agg < rec_trend_steps:
                trend_gap = (
                    f"Exact small-n permutation p-value active "
                    f"({n_agg} < {rec_trend_steps} asymptotic floor)."
                )
                trend_rem = (
                    f"Extend window to >= {rec_trend_steps} steps for tighter statistical power."
                )

            criteria.append(
                ReadinessCriterion(
                    criterion_id=f"trend_samples:{ds.dataset_id}:{var_name}",
                    category="trend",
                    dataset_id=ds.dataset_id,
                    variable_name=var_name,
                    stage_or_metric="Mann-Kendall & Sen's Slope",
                    title=f"{var_name} Trend Sample Size",
                    required_summary=(
                        f">= {min_trend_req} {request.target_cadence.value} steps "
                        f"(recommended >= {rec_trend_steps})"
                    ),
                    actual_summary=(
                        f"{n_agg} valid {request.target_cadence.value} steps "
                        f"({_format_span(span_yr)})"
                    ),
                    required_value=min_trend_req,
                    actual_value=n_agg,
                    unit="steps",
                    status=trend_status,
                    scientific_rationale=trend_rationale,
                    missing_gap=trend_gap,
                    remediation=trend_rem,
                )
            )

            eff_tr_grp = request.trend.seasonal_grouping
            if (
                t_res.cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}
                and eff_tr_grp == SeasonalGrouping.CALENDAR_MONTH
            ):
                eff_tr_grp = SeasonalGrouping.COMPOSITE_DOY_BIN
            tr_keys, _ = seasonal_group_keys(
                valid_ts, eff_tr_grp, composite_days=ds.temporal_metadata.composite_days
            )
            season_counts: dict[int, int] = defaultdict(int)
            for gk in tr_keys:
                season_counts[gk] += 1
            eligible_seasons = sum(1 for c in season_counts.values() if c >= 2)
            smk_ok = n_agg >= min_trend_req and eligible_seasons >= 1
            smk_status: CriterionStatus = (
                "failed" if not smk_ok else ("warning" if eligible_seasons < 4 else "passed")
            )
            smk_rem = (
                None
                if smk_ok
                else f"Expand window across >= 2 yr (archive {profile.earliest_archive_year}+)."
            )
            criteria.append(
                ReadinessCriterion(
                    criterion_id=f"seasonal_trend:{ds.dataset_id}:{var_name}",
                    category="trend",
                    dataset_id=ds.dataset_id,
                    variable_name=var_name,
                    stage_or_metric="Seasonal Mann-Kendall",
                    title=f"{var_name} Multi-Year Seasonal Strata",
                    required_summary=(
                        f">= {min_trend_req} steps spanning >= 1 repeating season bin (>= 2 yr)"
                    ),
                    actual_summary=(
                        f"{eligible_seasons} seasonal strata with >= 2 years "
                        f"({_format_span(span_yr)})"
                    ),
                    required_value=1,
                    actual_value=eligible_seasons,
                    unit="strata",
                    status=smk_status,
                    scientific_rationale=(
                        "Hirsch-Slack Seasonal Mann-Kendall computes within-season slopes across "
                        "repeating years; strata with 1 year cannot evaluate inter-annual change."
                    ),
                    missing_gap=(
                        None
                        if smk_ok
                        else "Observations do not repeat across >= 2 years within any season bin."
                    ),
                    remediation=smk_rem,
                )
            )

            eff_base_grp = request.baseline.seasonal_grouping
            if (
                t_res.cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}
                and eff_base_grp == SeasonalGrouping.CALENDAR_MONTH
            ):
                eff_base_grp = SeasonalGrouping.COMPOSITE_DOY_BIN
            base_cfg = request.baseline.model_copy(update={"seasonal_grouping": eff_base_grp})
            if t_res.timestamps:
                ref_mask, ref_warnings, ref_start_eff, ref_end_eff = select_reference_mask(
                    t_res.timestamps,
                    base_cfg,
                    assessment_start=request.analysis_start,
                    assessment_end=request.analysis_end,
                )
            else:
                ref_mask = []
                ref_warnings = []
                ref_start_eff = request.baseline.start or request.analysis_start
                ref_end_eff = request.baseline.end or request.analysis_end

            ref_years: set[int] = set()
            ref_bins: dict[int, int] = defaultdict(int)
            bkeys, _ = seasonal_group_keys(
                t_res.timestamps, eff_base_grp, composite_days=ds.temporal_metadata.composite_days
            )
            for keep, ts, val, gk in zip(
                ref_mask, t_res.timestamps, t_res.values, bkeys, strict=True
            ):
                if keep and val is not None and np.isfinite(val):
                    ref_years.add(ensure_utc(ts).year)
                    ref_bins[gk] += 1

            n_ref_years = len(ref_years)
            expected_bins = set(bkeys)
            suff_bins = sum(1 for gk in expected_bins if ref_bins.get(gk, 0) >= min_bin_samples_req)
            base_ok = (
                n_ref_years >= min_years_req
                and len(expected_bins) > 0
                and suff_bins == len(expected_bins)
            )
            base_gap: str | None = None
            base_rem: str | None = None
            if not base_ok:
                deficit_yrs = max(0, min_years_req - n_ref_years)
                if deficit_yrs == 0 and len(expected_bins) > suff_bins:
                    deficit_yrs = 1
                anchor_dt = (
                    request.analysis_start
                    if request.baseline.baseline_type
                    in {BaselineType.FIXED_REFERENCE, BaselineType.OUT_OF_SAMPLE}
                    else (min(valid_ts) if valid_ts else request.analysis_start)
                )
                target_start = _subtract_years(
                    anchor_dt,
                    max(deficit_yrs, min_years_req),
                )
                earliest_dt = datetime(profile.earliest_archive_year, 1, 1, tzinfo=UTC)
                eff_suggest = max(target_start, earliest_dt)
                suggested_starts.append(eff_suggest)
                if n_ref_years == 0 and request.baseline.baseline_type in {
                    BaselineType.FIXED_REFERENCE,
                    BaselineType.OUT_OF_SAMPLE,
                }:
                    base_gap = (
                        f"0 valid reference years found inside "
                        f"{ref_start_eff:%Y-%m-%d}..{ref_end_eff:%Y-%m-%d} "
                        "(or baseline overlaps assessment period)."
                    )
                    base_rem = (
                        f"Provision historical data covering >= {min_years_req} years before "
                        f"{request.analysis_start:%Y-%m-%d}, or use 'full_period_explicit' over "
                        f">= {min_years_req} years."
                    )
                else:
                    base_gap = (
                        f"Reference has {n_ref_years} year(s) (need >= {min_years_req}); "
                        f"{suff_bins}/{len(expected_bins)} bin(s) reach "
                        f">= {min_bin_samples_req} samples."
                    )
                    base_rem = (
                        f"Expand period start to <= {eff_suggest:%Y-%m-%d} for "
                        f">= {min_years_req} years ({eff_base_grp.value} climatology)."
                    )
                _add_action(base_rem)
            elif any("overlap" in w.lower() for w in ref_warnings):
                base_gap = "; ".join(ref_warnings)

            criteria.append(
                ReadinessCriterion(
                    criterion_id=f"baseline:{ds.dataset_id}:{var_name}",
                    category="baseline",
                    dataset_id=ds.dataset_id,
                    variable_name=var_name,
                    stage_or_metric="Climatology Baseline & Anomalies",
                    title=f"{var_name} Reference Baseline Years",
                    required_summary=(
                        f">= {min_years_req} distinct years & >= {min_bin_samples_req} "
                        f"samples/stratum ({eff_base_grp.value})"
                    ),
                    actual_summary=(
                        f"{n_ref_years} year(s), {suff_bins}/{len(expected_bins)} sufficient "
                        f"{eff_base_grp.value} strata"
                    ),
                    required_value=min_years_req,
                    actual_value=n_ref_years,
                    unit="years",
                    status="passed" if base_ok else "failed",
                    scientific_rationale=base_rationale,
                    missing_gap=base_gap,
                    remediation=base_rem,
                )
            )

        ds_status: ReadinessLevel
        if not ds_any_sufficient:
            ds_status = "insufficient"
        elif ds_all_sufficient and max(ds_spans or [0.0]) >= min_years_req:
            ds_status = "ready"
        else:
            ds_status = "partial"

        dataset_profiles.append(
            DatasetReadinessProfile(
                dataset_id=ds.dataset_id,
                source_id=ds.source_id,
                product=ds.product,
                variables=var_names,
                native_cadence=ds.temporal_metadata.cadence,
                target_cadence=request.target_cadence,
                observation_start=min(ds_ts_all) if ds_ts_all else ds.temporal_metadata.start,
                observation_end=max(ds_ts_all) if ds_ts_all else ds.temporal_metadata.end,
                span_years=round(max(ds_spans) if ds_spans else 0.0, 3),
                raw_step_count=max(ds_raw_counts) if ds_raw_counts else 0,
                valid_qa_count=max(ds_valid_counts) if ds_valid_counts else 0,
                valid_fraction=round(min(ds_valid_fracs) if ds_valid_fracs else 0.0, 4),
                qa_layers_present=qa_layers_present,
                has_grid_stack=has_stack,
                min_qa_fraction_required=round(min_qa_req, 3),
                min_step_coverage_required=round(min_agg_cov, 3),
                min_trend_samples_required=min_trend_req,
                min_baseline_years_required=min_years_req,
                status=ds_status,
                notes=ds_notes,
            )
        )

    cv_enabled = _stage_enabled(request, "cross_variable_analysis")
    cv_ok = False
    cv_gap: str | None = None
    cv_rem: str | None = None
    if len(evaluated_series) >= 2:
        has_gpm = any(ds.source_id == DataSourceId.GPM_IMERG for ds, *_ in evaluated_series)
        has_power_precip = any(
            ds.source_id == DataSourceId.NASA_POWER and "PRECTOTCORR" in vn.upper()
            for ds, vn, *_ in evaluated_series
        )
        if has_gpm and has_power_precip and not request.cross_variable.allow_power_precip_with_gpm:
            cv_gap = (
                "Mixes GPM IMERG and NASA POWER PRECTOTCORR while "
                "allow_power_precip_with_gpm=False."
            )
            cv_rem = (
                "Remove one redundant precipitation source or set allow_power_precip_with_gpm=True."
            )
            _add_action(cv_rem)
        else:
            ts_maps = [
                {
                    ensure_utc(ts)
                    for ts, v in zip(t_res.timestamps, t_res.values, strict=True)
                    if v is not None and np.isfinite(v)
                }
                for _, _, _, t_res in evaluated_series
            ]
            max_overlap = 0
            for i in range(len(ts_maps)):
                for j in range(i + 1, len(ts_maps)):
                    max_overlap = max(max_overlap, len(ts_maps[i] & ts_maps[j]))
            req_ov = request.cross_variable.min_overlap_samples
            if max_overlap >= req_ov:
                cv_ok = True
            else:
                cv_gap = f"Maximum aligned timestamp overlap is {max_overlap} (need >= {req_ov})."
                cv_rem = (
                    f"Use target_cadence='{request.target_cadence.value}' across >= {req_ov} "
                    "concurrent periods."
                )
                _add_action(cv_rem)

        criteria.append(
            ReadinessCriterion(
                criterion_id="cross_variable:alignment",
                category="cross_variable",
                stage_or_metric="Cross-Variable Correlation & Regression",
                title="Aligned Multi-Variable Overlap",
                required_summary=(
                    f">= 2 series with >= {request.cross_variable.min_overlap_samples} shared steps"
                ),
                actual_summary=(
                    f"{len(evaluated_series)} variables prepared"
                    + (
                        " (compatible overlap met)"
                        if cv_ok
                        else f" ({cv_gap or 'insufficient overlap'})"
                    )
                ),
                required_value=request.cross_variable.min_overlap_samples,
                actual_value=len(evaluated_series),
                unit="variables",
                status="passed" if cv_ok else "failed",
                scientific_rationale=(
                    "Cross-variable Pearson/Spearman and OLS require concurrent observations "
                    "on identical UTC timestamps and guard GPM IMERG vs MERRA-2 equivalence."
                ),
                missing_gap=cv_gap,
                remediation=cv_rem,
            )
        )
    else:
        cv_gap = "Only 1 validated variable is present (cross-variable analysis needs >= 2)."
        cv_rem = "Add a complementary dataset (e.g., NASA POWER meteorology alongside MODIS NDVI)."
        criteria.append(
            ReadinessCriterion(
                criterion_id="cross_variable:alignment",
                category="cross_variable",
                stage_or_metric="Cross-Variable Correlation & Regression",
                title="Multi-Variable Pairing",
                required_summary=">= 2 distinct variables on overlapping timestamps",
                actual_summary=f"{len(evaluated_series)} valid variable(s)",
                required_value=2,
                actual_value=len(evaluated_series),
                unit="variables",
                status="warning",
                scientific_rationale=(
                    "Cross-variable coupling is optional for single-variable assessments."
                ),
                missing_gap=cv_gap,
                remediation=cv_rem,
            )
        )

    sp_enabled = _stage_enabled(request, "spatial_analysis")
    has_any_stack = bool(stacks)
    criteria.append(
        ReadinessCriterion(
            criterion_id="spatial:grid_stacks",
            category="spatial",
            stage_or_metric="Spatial Zonal Statistics & Pixel Trends",
            title="3D Gridded GeoTIFF Raster Stack",
            required_summary=">= 1 gridded raster GeoTIFF asset (optional P0 spatial stage)",
            actual_summary=(
                f"{len(stacks)} gridded raster stack(s) attached"
                if has_any_stack
                else "Time-series-only inputs (0 raster stacks)"
            ),
            required_value=1,
            actual_value=len(stacks),
            unit="stacks",
            status="passed" if has_any_stack else "warning",
            scientific_rationale=(
                "Pixel-wise Mann-Kendall FDR maps and Moran's I require 2D spatial grids over "
                "time; point/AOI-reduced sources like NASA POWER provide 1D AOI series only."
            ),
            missing_gap=(
                None if has_any_stack else "No 3D GeoTIFF grids attached; pixel stage skipped."
            ),
            remediation=(
                None
                if has_any_stack
                else "Include spatially gridded MODIS/SMAP/IMERG GeoTIFFs for spatial hotspot maps."
            ),
        )
    )

    any_qa_ok = len(evaluated_series) > 0
    any_trend_ok = any(
        c.criterion_id.startswith("trend_samples:") and c.status in {"passed", "warning"}
        for c in criteria
    )
    any_smk_ok = any(
        c.criterion_id.startswith("seasonal_trend:") and c.status in {"passed", "warning"}
        for c in criteria
    )
    any_base_ok = any(c.category == "baseline" and c.status == "passed" for c in criteria)
    max_steps = max(
        (
            sum(1 for v in t_res.values if v is not None and np.isfinite(v))
            for _, _, _, t_res in evaluated_series
        ),
        default=0,
    )
    dist_min_req = max(request.disturbance.min_segment_length * 2, 6)
    dist_ok = max_steps >= dist_min_req

    metrics: list[MetricAvailability] = [
        MetricAvailability(
            metric_id="qa_screening",
            label="QA Bitmask & Physical Bounds Screening",
            priority=PriorityTier.P0,
            status="available" if any_qa_ok else "unavailable",
            blocking_criteria=[
                c.criterion_id
                for c in criteria
                if c.category == "data_quality" and c.status == "failed"
            ],
            reason=(
                "Source QA screening passed for one or more variables."
                if any_qa_ok
                else "All datasets failed QA coverage or physical bounds screening."
            ),
            remediation=None if any_qa_ok else "Expand date window or ingest QA-validated data.",
        ),
        MetricAvailability(
            metric_id="temporal_aggregation",
            label="Interval-Preserving Temporal Series",
            priority=PriorityTier.P0,
            status="available" if any_qa_ok else "unavailable",
            blocking_criteria=[] if any_qa_ok else ["datasets:presence"],
            reason=(
                f"Harmonizes valid observations to {request.target_cadence.value} cadence."
                if any_qa_ok
                else "Requires at least one QA-valid observation series."
            ),
        ),
        MetricAvailability(
            metric_id="baseline_climatology",
            label="Seasonal Climatology Baseline & Z-Score Anomalies",
            priority=PriorityTier.P0,
            status="available" if any_base_ok else ("degraded" if any_qa_ok else "unavailable"),
            blocking_criteria=[
                c.criterion_id
                for c in criteria
                if c.category == "baseline" and c.status == "failed"
            ],
            reason=(
                "Reference climatology strata satisfy multi-year sample requirements."
                if any_base_ok
                else (
                    f"Insufficient reference years (need >= {min_years_req} yr with "
                    f">= {min_bin_samples_req} samples/stratum); climatology flagged insufficient."
                )
            ),
            remediation=(
                None
                if any_base_ok
                else f"Expand date range to >= {min_years_req} years across repeating seasons."
            ),
        ),
        MetricAvailability(
            metric_id="trend_mann_kendall",
            label="Mann-Kendall Monotonic Trend & Sen's Slope",
            priority=PriorityTier.P0,
            status=(
                "available"
                if (any_trend_ok and _stage_enabled(request, "trend_analysis"))
                else "unavailable"
            ),
            blocking_criteria=[
                c.criterion_id
                for c in criteria
                if c.criterion_id.startswith("trend_samples:") and c.status == "failed"
            ],
            reason=(
                f"Computable on >= {min_trend_req} valid {request.target_cadence.value} steps."
                if any_trend_ok
                else f"Fewer than {min_trend_req} valid {request.target_cadence.value} steps."
            ),
            remediation=None if any_trend_ok else f"Collect >= {min_trend_req} valid steps.",
        ),
        MetricAvailability(
            metric_id="seasonal_mann_kendall",
            label="Hirsch-Slack Seasonal Mann-Kendall",
            priority=PriorityTier.P0,
            status="available" if any_smk_ok else "unavailable",
            blocking_criteria=[
                c.criterion_id
                for c in criteria
                if c.criterion_id.startswith("seasonal_trend:") and c.status == "failed"
            ],
            reason=(
                "Repeating multi-year seasonal strata present."
                if any_smk_ok
                else "Requires repeating seasonal observations across >= 2 distinct years."
            ),
        ),
        MetricAvailability(
            metric_id="spatial_analysis",
            label="Zonal Statistics, Pixel Trends (FDR) & Moran's I",
            priority=PriorityTier.P0,
            required=sp_enabled and has_any_stack,
            status="available" if (sp_enabled and has_any_stack) else "unavailable",
            blocking_criteria=[] if (sp_enabled and has_any_stack) else ["spatial:grid_stacks"],
            reason=(
                "Gridded raster stacks available for zonal & pixel statistics."
                if has_any_stack
                else "No 3D GeoTIFF stacks supplied (runs time-series assessment cleanly)."
            ),
        ),
        MetricAvailability(
            metric_id="cross_variable_association",
            label="Cross-Variable Correlation, Lagged Response & OLS",
            priority=PriorityTier.P1,
            required=cv_enabled and len(evaluated_series) >= 2,
            status="available" if (cv_enabled and cv_ok) else "unavailable",
            blocking_criteria=[] if cv_ok else ["cross_variable:alignment"],
            reason=(
                "Compatible overlapping multi-variable series available."
                if cv_ok
                else (cv_gap or "Needs >= 2 aligned compatible datasets.")
            ),
            remediation=cv_rem,
        ),
        MetricAvailability(
            metric_id="disturbance_and_recovery",
            label="Pettitt Change-Points, Disturbance Runs & Event Recovery",
            priority=PriorityTier.P1,
            status=(
                "available"
                if (any_base_ok and dist_ok)
                else ("degraded" if any_qa_ok and max_steps >= 6 else "unavailable")
            ),
            blocking_criteria=[
                c.criterion_id
                for c in criteria
                if c.category == "baseline" and c.status == "failed"
            ],
            reason=(
                "Change-point segmentation and anomaly event recovery active."
                if (any_base_ok and dist_ok)
                else (
                    f"Pettitt test requires >= {dist_min_req} steps; event recovery additionally "
                    "depends on a sufficient baseline climatology."
                )
            ),
        ),
        MetricAvailability(
            metric_id="resilience_dimensions",
            label="Resilience Dimensions (Resistance, Recovery, Stability, Sensitivity)",
            priority=PriorityTier.P1,
            status=(
                "available"
                if any_base_ok
                else ("degraded" if any_qa_ok and max_steps >= 4 else "unavailable")
            ),
            reason=(
                "Stability and event-anchored resistance/recovery available when events occur."
                if any_base_ok
                else (
                    "Stability uses available residuals; "
                    "resistance/recovery require baseline anomalies."
                )
            ),
        ),
        MetricAvailability(
            metric_id="composite_tri",
            label="Composite TERRA Resilience Index (TRI)",
            priority=PriorityTier.P2,
            required=False,
            status="deferred",
            reason=(
                "Explicitly deferred in P0/P1 Scientific Core pending ecological calibration "
                "and out-of-sample validation."
            ),
        ),
    ]

    overall: ReadinessLevel
    if not any_qa_ok or (not any_base_ok and not any_trend_ok and not has_any_stack):
        overall = "insufficient"
        summary = (
            "Insufficient data: primary quantitative stages (baseline, trend, spatial) do not "
            "meet minimum scientific requirements."
        )
    elif all(
        c.status in {"passed", "warning"}
        for c in criteria
        if c.category in {"data_quality", "baseline", "trend"}
    ):
        overall = "ready"
        summary = (
            f"Ready: {len(evaluated_series)} variable series satisfy source-specific QA, "
            "baseline, and trend criteria."
        )
    else:
        overall = "partial"
        avail_labels = [
            m.label for m in metrics if m.status == "available" and m.priority == PriorityTier.P0
        ]
        degraded_labels = [
            m.label
            for m in metrics
            if m.status in {"degraded", "unavailable"} and m.priority == PriorityTier.P0
        ]
        summary = (
            f"Partial readiness: {', '.join(avail_labels) or 'QA screening'} available; "
            f"limited or unavailable: {', '.join(degraded_labels) or 'optional P1 stages'}."
        )

    return ReadinessAssessmentReport(
        overall_status=overall,
        summary=summary,
        datasets=dataset_profiles,
        criteria=criteria,
        metrics=metrics,
        recommended_actions=actions,
        suggested_window_start=min(suggested_starts) if suggested_starts else None,
        suggested_window_end=request.analysis_end if suggested_starts else None,
    )
