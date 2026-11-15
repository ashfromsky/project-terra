"""End-to-end deterministic Scientific Assessment orchestration service."""

import contextlib
import hashlib
import importlib.metadata
import json
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
import pydantic
import scipy
from numpy.typing import NDArray

from terra_scientific._version import __version__ as PACKAGE_VERSION
from terra_scientific.anomalies.detector import detect_anomalies
from terra_scientific.baselines.climatology import compute_climatology
from terra_scientific.cross_variable.analysis import SeriesBundle, analyze_cross_variables
from terra_scientific.disturbances.detector import detect_disturbances
from terra_scientific.domain.contracts import ArtifactWriterPort
from terra_scientific.domain.enums import (
    AggregationOperator,
    AssessmentStatus,
    DataSourceId,
    PriorityTier,
    SeasonalGrouping,
    StageStatus,
    TemporalCadence,
)
from terra_scientific.domain.exceptions import ScientificCoreError, ScientificInputError
from terra_scientific.domain.models.dataset import (
    ScientificDataset,
    ScientificGridStack,
    VariableMetadata,
)
from terra_scientific.domain.models.provenance import (
    DatasetLineageEntry,
    MethodReference,
    ProvenanceTrace,
)
from terra_scientific.domain.models.quality import QualitySummary
from terra_scientific.domain.models.request import AssessmentRequest
from terra_scientific.domain.models.result import (
    AnomalyResult,
    BaselineClimatologyResult,
    CrossVariableResult,
    DisturbanceResult,
    RecoveryEventResult,
    ResilienceMetricsResult,
    ScientificAssessmentResult,
    SeasonalTrendResult,
    SpatialStatsResult,
    StageExecutionReport,
    TemporalSeriesResult,
    TrendResult,
)
from terra_scientific.methods.registry import DEFAULT_METHOD_REGISTRY
from terra_scientific.pipeline.artifacts import JsonArtifactWriter
from terra_scientific.quality.validator import screen_dataset_variable, screen_grid_stack
from terra_scientific.recovery.analyzer import analyze_post_event_recovery
from terra_scientific.resilience.metrics import compute_resilience_dimensions
from terra_scientific.spatial.autocorrelation import compute_morans_i_and_hotspots
from terra_scientific.spatial.pixel_trends import compute_chunked_pixel_trends
from terra_scientific.spatial.support_guard import check_spatial_support_compatibility
from terra_scientific.spatial.zonal import compute_zonal_statistics, extract_area_weighted_series
from terra_scientific.temporal.aggregation import aggregate_temporal_series
from terra_scientific.temporal.interpolation import interpolate_gaps_explicit
from terra_scientific.trends.mann_kendall import compute_mann_kendall
from terra_scientific.trends.seasonal_mk import compute_seasonal_mann_kendall
from terra_scientific.uncertainty.assessor import assess_uncertainty_and_sensitivity


@dataclass(slots=True)
class _PreparedVariable:
    key: str
    dataset: ScientificDataset
    variable_name: str
    var_meta: VariableMetadata
    quality: QualitySummary
    temporal: TemporalSeriesResult
    array: NDArray[np.float64]
    baseline: BaselineClimatologyResult | None = None
    anomaly: AnomalyResult | None = None
    trend: TrendResult | None = None
    seasonal_trend: SeasonalTrendResult | None = None


def _compute_input_digest(
    request: AssessmentRequest,
    datasets: list[ScientificDataset],
) -> str:
    manifest = {
        "request": request.model_dump(mode="json", exclude={"request_id"}),
        "datasets": sorted(
            [
                {
                    "dataset_id": d.dataset_id,
                    "product": d.product,
                    "version": d.product_version,
                    "vars": sorted(d.variables.keys()),
                    "start": d.temporal_metadata.start.isoformat(),
                    "end": d.temporal_metadata.end.isoformat(),
                }
                for d in datasets
            ],
            key=lambda item: str(item["dataset_id"]),
        ),
    }
    encoded = json.dumps(manifest, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_stage_enabled(request: AssessmentRequest, stage_name: str) -> bool:
    if request.enabled_stages is None:
        return True
    return stage_name in request.enabled_stages


class ScientificAssessmentService:
    """Runs deterministic P0 and P1 assessment stages with partial-data resilience."""

    def __init__(self, artifact_writer: ArtifactWriterPort | None = None) -> None:
        self._artifact_writer: ArtifactWriterPort = artifact_writer or JsonArtifactWriter()

    def run_assessment(
        self,
        request: AssessmentRequest,
        *,
        datasets: list[ScientificDataset],
        grid_stacks: dict[str, ScientificGridStack] | None = None,
        assessment_id: str | None = None,
    ) -> ScientificAssessmentResult:
        """Execute full Scientific Assessment pipeline returning traceable typed result."""
        run_id = assessment_id or f"assess-{uuid4().hex[:12]}"
        stages: list[StageExecutionReport] = []
        methods_invoked: list[MethodReference] = []
        lineage: list[DatasetLineageEntry] = []
        qa_policies_applied: list[str] = []
        harmonization_steps: list[str] = []
        summary_warnings: list[str] = []
        limitations: list[str] = []
        seen_limitations: set[str] = set()

        def _add_limitations(items: list[str]) -> None:
            for item in items:
                if item not in seen_limitations:
                    seen_limitations.add(item)
                    limitations.append(item)

        if not datasets:
            return ScientificAssessmentResult(
                assessment_id=run_id,
                request=request,
                status=AssessmentStatus.INSUFFICIENT_DATA,
                summary_warnings=["No quantitative datasets supplied to assessment pipeline."],
            )

        stacks = dict(grid_stacks or {})
        digest = _compute_input_digest(request, datasets)

        # Stage 1 & 2: Quality Screening & Temporal Harmonization
        t0 = time.perf_counter()
        quality_reports: dict[str, QualitySummary] = {}
        prepared: list[_PreparedVariable] = []
        partial_failures: list[str] = []
        interpolation_used = False

        for ds in datasets:
            _add_limitations(ds.limitations)
            var_names = list(ds.series.keys()) or [
                v for v in ds.variables if f"{ds.dataset_id}:{v}" in stacks or v in stacks
            ]
            if not var_names:
                partial_failures.append(f"Dataset '{ds.dataset_id}' contains no data variables.")
                continue

            for var_name in var_names:
                key = f"{ds.dataset_id}:{var_name}"
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
                        stacks[key] = screened_stack
                        raw_ts, screened_1d = extract_area_weighted_series(
                            screened_stack, min_spatial_coverage=request.spatial.min_pixel_coverage
                        )
                        var_meta = screened_stack.variable
                    else:
                        partial_failures.append(f"No series or grid payload for '{key}'.")
                        continue

                    quality_reports[key] = q_summary
                    qa_policies_applied.append(q_summary.qa_policy_applied)
                    lineage.append(
                        DatasetLineageEntry(
                            dataset_id=ds.dataset_id,
                            source_id=ds.source_id.value,
                            product=ds.product,
                            product_version=ds.product_version,
                            run_type=ds.run_type,
                            granule_ids=ds.granule_ids,
                            crs=ds.spatial_support.crs,
                            nominal_resolution_m=ds.spatial_support.nominal_resolution_m,
                            native_footprint_m=ds.spatial_support.native_footprint_m,
                            retrieval_timestamp=ds.retrieval_timestamp,
                            qa_policy_id=q_summary.qa_policy_applied,
                            ghs_dataset_id=ds.ghs_dataset_id,
                        )
                    )
                    if not q_summary.passed_sufficiency:
                        partial_failures.append(
                            f"Dataset '{key}' failed quality sufficiency "
                            f"(valid_fraction={q_summary.valid_fraction:.2f})."
                        )
                        continue

                    op = request.aggregation_operator
                    if ds.source_id == DataSourceId.GPM_IMERG and "hr" in var_meta.units.lower():
                        op = AggregationOperator.SUM
                        methods_invoked.append(
                            DEFAULT_METHOD_REGISTRY.get("imerg_rate_to_depth").to_reference(
                                {"interval_hours": 0.5}
                            )
                        )
                        harmonization_steps.append(f"{key}: converted IMERG rate (mm/hr) to mm")

                    min_cov = 0.5 if ds.source_id == DataSourceId.GPM_IMERG else 0.7
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
                    arr = np.array(
                        [np.nan if v is None else float(v) for v in temp_res.values],
                        dtype=np.float64,
                    )
                    if request.allow_interpolation and np.any(~np.isfinite(arr)):
                        filled, interp_idx, interp_note = interpolate_gaps_explicit(
                            temp_res.timestamps, arr
                        )
                        if interp_idx:
                            interpolation_used = True
                            arr = filled
                            temp_res = temp_res.model_copy(
                                update={
                                    "values": [None if np.isnan(v) else float(v) for v in filled],
                                    "interpolation_applied": True,
                                    "interpolated_indices": interp_idx,
                                    "warnings": [*temp_res.warnings, interp_note],
                                }
                            )
                            harmonization_steps.append(f"{key}: {interp_note}")

                    prepared.append(
                        _PreparedVariable(
                            key=key,
                            dataset=ds,
                            variable_name=var_name,
                            var_meta=var_meta.model_copy(update={"units": temp_res.units}),
                            quality=q_summary,
                            temporal=temp_res,
                            array=arr,
                        )
                    )
                except ScientificCoreError as exc:
                    if not request.allow_partial_datasets:
                        raise
                    partial_failures.append(f"{key}: {exc}")

        methods_invoked.append(
            DEFAULT_METHOD_REGISTRY.get("qa_screening").to_reference(
                {"qa_level": request.qa_level.value}
            )
        )
        stages.append(
            StageExecutionReport(
                stage_name="quality_and_temporal",
                priority=PriorityTier.P0,
                status=(
                    StageStatus.INSUFFICIENT_DATA
                    if not prepared
                    else (StageStatus.PARTIAL if partial_failures else StageStatus.COMPLETED)
                ),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                warnings=partial_failures,
            )
        )

        if not prepared:
            return ScientificAssessmentResult(
                assessment_id=run_id,
                request=request,
                status=AssessmentStatus.INSUFFICIENT_DATA,
                quality_reports=quality_reports,
                stages=stages,
                summary_warnings=partial_failures,
                limitations=limitations,
                provenance=ProvenanceTrace(
                    trace_id=f"trace-{run_id}",
                    package_version=PACKAGE_VERSION,
                    dataset_lineage=lineage,
                    qa_policies_applied=sorted(set(qa_policies_applied)),
                    methods_invoked=methods_invoked,
                    software_versions=_software_versions(),
                    input_digest_sha256=digest,
                ),
            )

        # Stage 3 & 4: Baselines & Anomalies
        t_base = time.perf_counter()
        baselines: list[BaselineClimatologyResult] = []
        anomalies: list[AnomalyResult] = []
        base_warnings: list[str] = []
        for pv in prepared:
            comp_days = pv.dataset.temporal_metadata.composite_days
            eff_grouping = request.baseline.seasonal_grouping
            if (
                pv.temporal.cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}
                and eff_grouping == SeasonalGrouping.CALENDAR_MONTH
            ):
                eff_grouping = SeasonalGrouping.COMPOSITE_DOY_BIN
            base_cfg = request.baseline.model_copy(update={"seasonal_grouping": eff_grouping})
            clim = compute_climatology(
                timestamps=pv.temporal.timestamps,
                values=pv.array,
                config=base_cfg,
                variable_name=pv.variable_name,
                units=pv.var_meta.units,
                dataset_id=pv.dataset.dataset_id,
                composite_days=comp_days,
                assessment_start=request.analysis_start,
                assessment_end=request.analysis_end,
                raise_on_insufficient=False,
            )
            anom = detect_anomalies(
                timestamps=pv.temporal.timestamps,
                values=pv.array,
                climatology=clim,
                config=request.anomaly,
                composite_days=comp_days,
            )
            pv.baseline = clim
            pv.anomaly = anom
            baselines.append(clim)
            anomalies.append(anom)
            base_warnings.extend(clim.warnings)

        methods_invoked.append(
            DEFAULT_METHOD_REGISTRY.get("climatology_baseline").to_reference(
                request.baseline.model_dump(mode="json")
            )
        )
        methods_invoked.append(
            DEFAULT_METHOD_REGISTRY.get("anomaly_detection").to_reference(
                request.anomaly.model_dump(mode="json")
            )
        )
        stages.append(
            StageExecutionReport(
                stage_name="baseline_and_anomalies",
                priority=PriorityTier.P0,
                status=StageStatus.PARTIAL
                if any(not b.sufficient for b in baselines)
                else StageStatus.COMPLETED,
                duration_ms=(time.perf_counter() - t_base) * 1000.0,
                warnings=base_warnings,
            )
        )

        # Stage 5: Trends & Seasonal MK
        t_tr = time.perf_counter()
        trends: list[TrendResult] = []
        seasonal_trends: list[SeasonalTrendResult] = []
        if _is_stage_enabled(request, "trend_analysis"):
            for pv in prepared:
                tr = compute_mann_kendall(
                    pv.temporal.timestamps,
                    pv.array,
                    request.trend,
                    dataset_id=pv.dataset.dataset_id,
                    variable_name=pv.variable_name,
                    units=pv.var_meta.units,
                )
                eff_grp = request.trend.seasonal_grouping
                if (
                    pv.temporal.cadence in {TemporalCadence.EIGHT_DAY, TemporalCadence.SIXTEEN_DAY}
                    and eff_grp == SeasonalGrouping.CALENDAR_MONTH
                ):
                    eff_grp = SeasonalGrouping.COMPOSITE_DOY_BIN
                t_cfg = request.trend.model_copy(update={"seasonal_grouping": eff_grp})
                str_res = compute_seasonal_mann_kendall(
                    pv.temporal.timestamps,
                    pv.array,
                    t_cfg,
                    dataset_id=pv.dataset.dataset_id,
                    variable_name=pv.variable_name,
                    units=pv.var_meta.units,
                    composite_days=pv.dataset.temporal_metadata.composite_days,
                )
                pv.trend = tr
                pv.seasonal_trend = str_res
                trends.append(tr)
                seasonal_trends.append(str_res)

            methods_invoked.extend(
                [
                    DEFAULT_METHOD_REGISTRY.get("mann_kendall").to_reference(
                        {"alpha": request.trend.alpha}
                    ),
                    DEFAULT_METHOD_REGISTRY.get("seasonal_mann_kendall").to_reference(),
                    DEFAULT_METHOD_REGISTRY.get("sens_slope").to_reference(
                        {"time_unit": request.trend.slope_time_unit}
                    ),
                    DEFAULT_METHOD_REGISTRY.get("autocorrelation_diagnostics").to_reference(
                        {"policy": request.trend.autocorrelation_policy.value}
                    ),
                ]
            )
            stages.append(
                StageExecutionReport(
                    stage_name="trend_analysis",
                    priority=PriorityTier.P0,
                    status=StageStatus.COMPLETED,
                    duration_ms=(time.perf_counter() - t_tr) * 1000.0,
                )
            )
        else:
            stages.append(
                StageExecutionReport(
                    stage_name="trend_analysis",
                    priority=PriorityTier.P0,
                    status=StageStatus.SKIPPED,
                    duration_ms=0.0,
                )
            )

        # Stage 6: Spatial Statistics & Pixel Trends
        t_sp = time.perf_counter()
        spatial_stats: list[SpatialStatsResult] = []
        if _is_stage_enabled(request, "spatial_analysis") and stacks:
            for stack_key, stack in stacks.items():
                try:
                    screened_st, _ = screen_grid_stack(
                        stack, qa_level=request.qa_level, run_type=None
                    )
                    zonal = compute_zonal_statistics(screened_st)
                    pix_fdr_frac: float | None = None
                    pix_pos_frac: float | None = None
                    pix_neg_frac: float | None = None
                    moran_i: float | None = None
                    moran_z: float | None = None
                    moran_p: float | None = None
                    hot_f: float | None = None
                    cold_f: float | None = None

                    if (
                        request.spatial.compute_pixel_trends
                        and screened_st.data.shape[0] >= request.trend.min_samples
                    ):
                        pt = compute_chunked_pixel_trends(
                            screened_st, trend_config=request.trend, spatial_config=request.spatial
                        )
                        pix_fdr_frac = pt.fdr_significant_fraction
                        pix_pos_frac = pt.positive_fraction
                        pix_neg_frac = pt.negative_fraction
                        surface_2d = pt.slopes
                    else:
                        surface_2d = np.nanmean(screened_st.data, axis=0)

                    if request.spatial.compute_autocorrelation:
                        ac = compute_morans_i_and_hotspots(
                            surface_2d,
                            alpha=request.trend.alpha,
                            permutations=request.spatial.permutations,
                        )
                        moran_i = ac.morans_i
                        moran_z = ac.morans_z
                        moran_p = ac.morans_p_value
                        hot_f = ac.hotspot_significant_fraction
                        cold_f = ac.coldspot_significant_fraction

                    spatial_stats.append(
                        zonal.model_copy(
                            update={
                                "morans_i": moran_i,
                                "morans_z": moran_z,
                                "morans_p_value": moran_p,
                                "hotspot_significant_fraction": hot_f,
                                "coldspot_significant_fraction": cold_f,
                                "pixel_trend_significant_fdr_fraction": pix_fdr_frac,
                                "pixel_trend_positive_fraction": pix_pos_frac,
                                "pixel_trend_negative_fraction": pix_neg_frac,
                            }
                        )
                    )
                except ScientificCoreError as exc:
                    summary_warnings.append(f"Spatial stack '{stack_key}': {exc}")

            methods_invoked.extend(
                [
                    DEFAULT_METHOD_REGISTRY.get("spatial_zonal_stats").to_reference(),
                    DEFAULT_METHOD_REGISTRY.get("benjamini_hochberg_fdr").to_reference(),
                    DEFAULT_METHOD_REGISTRY.get("spatial_autocorrelation").to_reference(),
                ]
            )
            stages.append(
                StageExecutionReport(
                    stage_name="spatial_analysis",
                    priority=PriorityTier.P0,
                    status=StageStatus.COMPLETED if spatial_stats else StageStatus.SKIPPED,
                    duration_ms=(time.perf_counter() - t_sp) * 1000.0,
                )
            )
        else:
            stages.append(
                StageExecutionReport(
                    stage_name="spatial_analysis",
                    priority=PriorityTier.P0,
                    status=StageStatus.SKIPPED,
                    duration_ms=0.0,
                    skip_reason="No 3D gridded raster stacks provided.",
                )
            )

        # Check pairwise spatial support disparities across datasets
        for idx_a in range(len(datasets)):
            for idx_b in range(idx_a + 1, len(datasets)):
                summary_warnings.extend(
                    check_spatial_support_compatibility(
                        datasets[idx_a].product,
                        datasets[idx_a].spatial_support,
                        datasets[idx_b].product,
                        datasets[idx_b].spatial_support,
                    )
                )

        # Stage 7: Cross-Variable Analysis
        t_cv = time.perf_counter()
        cross_var: CrossVariableResult | None = None
        if _is_stage_enabled(request, "cross_variable_analysis") and len(prepared) >= 2:
            # Prefer vegetation index (MOD13 NDVI/EVI) as biological response variable.
            resp_pv = next(
                (p for p in prepared if p.dataset.source_id == DataSourceId.MODIS_MOD13Q1),
                prepared[0],
            )
            pred_map: dict[str, SeriesBundle] = {
                p.key: (
                    p.temporal.timestamps,
                    p.array,
                    p.var_meta,
                    p.dataset.source_id,
                    p.dataset.spatial_support.native_footprint_m
                    or p.dataset.spatial_support.nominal_resolution_m,
                )
                for p in prepared
                if p.key != resp_pv.key
            }
            resp_bundle: SeriesBundle = (
                resp_pv.temporal.timestamps,
                resp_pv.array,
                resp_pv.var_meta,
                resp_pv.dataset.source_id,
                resp_pv.dataset.spatial_support.native_footprint_m
                or resp_pv.dataset.spatial_support.nominal_resolution_m,
            )
            try:
                cross_var = analyze_cross_variables(
                    response_name=resp_pv.key,
                    response_series=resp_bundle,
                    predictors=pred_map,
                    config=request.cross_variable,
                )
                methods_invoked.append(
                    DEFAULT_METHOD_REGISTRY.get("cross_variable_association").to_reference(
                        request.cross_variable.model_dump(mode="json")
                    )
                )
                stages.append(
                    StageExecutionReport(
                        stage_name="cross_variable_analysis",
                        priority=PriorityTier.P1,
                        status=StageStatus.COMPLETED,
                        duration_ms=(time.perf_counter() - t_cv) * 1000.0,
                        warnings=cross_var.warnings,
                    )
                )
            except ScientificInputError as exc:
                summary_warnings.append(str(exc))
                stages.append(
                    StageExecutionReport(
                        stage_name="cross_variable_analysis",
                        priority=PriorityTier.P1,
                        status=StageStatus.FAILED,
                        duration_ms=(time.perf_counter() - t_cv) * 1000.0,
                        errors=[str(exc)],
                    )
                )
        else:
            stages.append(
                StageExecutionReport(
                    stage_name="cross_variable_analysis",
                    priority=PriorityTier.P1,
                    status=StageStatus.SKIPPED,
                    duration_ms=0.0,
                    skip_reason="Requires >= 2 compatible variable series.",
                )
            )

        # Stage 8, 9 & 10: Disturbance, Event Recovery & Resilience Dimensions
        t_dist = time.perf_counter()
        disturbances: list[DisturbanceResult] = []
        recoveries: list[RecoveryEventResult] = []
        resilience_list: list[ResilienceMetricsResult] = []

        for pv in prepared:
            if pv.anomaly is None:
                continue
            raw_anom = [None if v is None else float(v) for v in pv.anomaly.raw_anomalies]
            use_robust = request.anomaly.use_robust_default
            primary_z = pv.anomaly.robust_zscores if use_robust else pv.anomaly.standard_zscores
            fallback_z = pv.anomaly.standard_zscores if use_robust else pv.anomaly.robust_zscores
            z_series = [
                p if p is not None else f for p, f in zip(primary_z, fallback_z, strict=True)
            ]
            dist = detect_disturbances(
                pv.temporal.timestamps,
                pv.array,
                z_series,
                request.disturbance,
                dataset_id=pv.dataset.dataset_id,
                variable_name=pv.variable_name,
            )
            disturbances.append(dist)

            pv_rec: list[RecoveryEventResult] = []
            neg_runs = [
                r
                for r in dist.candidate_disturbance_runs
                if r.polarity == "negative_anomaly"
                and r.peak_zscore < 0.0
                and (
                    request.disturbance.negative_z_threshold >= 0.0
                    or r.peak_zscore <= request.disturbance.negative_z_threshold
                )
            ]
            ts_index = {ts: idx for idx, ts in enumerate(pv.temporal.timestamps)}
            indexed_neg_runs = sorted(
                [
                    (ts_index[r.start_timestamp], r)
                    for r in neg_runs
                    if r.start_timestamp in ts_index
                ],
                key=lambda item: item[0],
            )
            eligible_neg_runs = [r for _, r in indexed_neg_runs]
            for pos, (s_idx, _run) in enumerate(indexed_neg_runs):
                next_idx = indexed_neg_runs[pos + 1][0] if pos + 1 < len(indexed_neg_runs) else None
                ev_rec = analyze_post_event_recovery(
                    pv.temporal.timestamps,
                    raw_anom,
                    event_start_idx=s_idx,
                    next_event_idx=next_idx,
                    config=request.recovery,
                    dataset_id=pv.dataset.dataset_id,
                    variable_name=pv.variable_name,
                    unit_label=pv.var_meta.units,
                    is_deseasonalized=True,
                )
                pv_rec.append(ev_rec)
                recoveries.append(ev_rec)

            sens_slope: float | None = None
            sens_driver: str | None = None
            sens_unit = f"{pv.var_meta.units}/driver"
            if cross_var is not None and cross_var.pairwise:
                candidate_pairs = [
                    pair
                    for pair in cross_var.pairwise
                    if pair.response_variable == pv.key
                    and pair.ols_slope is not None
                    and np.isfinite(pair.ols_slope)
                ]
                if candidate_pairs:
                    top_pair = max(
                        candidate_pairs,
                        key=lambda pair: abs(pair.pearson_r or 0.0),
                    )
                    if top_pair.ols_slope is not None:
                        sens_slope = float(top_pair.ols_slope)
                        sens_driver = top_pair.driver_variable
                        if top_pair.slope_unit:
                            sens_unit = top_pair.slope_unit

            if request.resilience.compute_dimensions:
                res_dim = compute_resilience_dimensions(
                    dataset_id=pv.dataset.dataset_id,
                    variable_name=pv.variable_name,
                    deseasonalized_residuals=raw_anom,
                    standardized_residuals=z_series,
                    zscores=z_series,
                    timestamps=pv.temporal.timestamps,
                    disturbance_runs=eligible_neg_runs,
                    recovery_events=pv_rec,
                    sensitivity_slope=sens_slope,
                    sensitivity_driver=sens_driver,
                    sensitivity_unit=sens_unit,
                )
                resilience_list.append(res_dim)

        methods_invoked.extend(
            [
                DEFAULT_METHOD_REGISTRY.get("pettitt_change_point").to_reference(),
                DEFAULT_METHOD_REGISTRY.get("event_recovery").to_reference(),
                DEFAULT_METHOD_REGISTRY.get("resilience_dimensions").to_reference(),
            ]
        )
        stages.append(
            StageExecutionReport(
                stage_name="disturbance_recovery_resilience",
                priority=PriorityTier.P1,
                status=StageStatus.COMPLETED,
                duration_ms=(time.perf_counter() - t_dist) * 1000.0,
            )
        )

        # Stage 11: Uncertainty & Sensitivity
        primary_pv = prepared[0]
        uncertainty = assess_uncertainty_and_sensitivity(
            sources=[(pv.dataset.source_id, pv.dataset.product, pv.quality) for pv in prepared],
            trends=trends,
            timestamps=primary_pv.temporal.timestamps,
            series_values=primary_pv.array,
            trend_config=request.trend,
            has_cross_variable=cross_var is not None,
            interpolation_used=interpolation_used,
        )
        _add_limitations(uncertainty.methodological_limitations)

        overall_status = (
            AssessmentStatus.COMPLETED_PARTIAL if partial_failures else AssessmentStatus.COMPLETED
        )

        provenance = ProvenanceTrace(
            trace_id=f"trace-{run_id}",
            package_version=PACKAGE_VERSION,
            dataset_lineage=lineage,
            harmonization_steps=harmonization_steps,
            qa_policies_applied=sorted(set(qa_policies_applied)),
            methods_invoked=methods_invoked,
            software_versions=_software_versions(),
            input_digest_sha256=digest,
            deterministic_seed=42,
        )

        result = ScientificAssessmentResult(
            assessment_id=run_id,
            request=request,
            status=overall_status,
            quality_reports=quality_reports,
            temporal_series=[pv.temporal for pv in prepared],
            baselines=baselines,
            anomalies=anomalies,
            trends=trends,
            seasonal_trends=seasonal_trends,
            spatial_stats=spatial_stats,
            cross_variable=cross_var,
            disturbances=disturbances,
            recoveries=recoveries,
            resilience=resilience_list,
            uncertainty=uncertainty,
            stages=stages,
            provenance=provenance,
            summary_warnings=summary_warnings,
            limitations=limitations,
        )

        if request.output_artifact_dir is not None:
            manifest = self._artifact_writer.write_assessment_result(
                result, Path(request.output_artifact_dir)
            )
            result = result.model_copy(update={"artifact_manifest": manifest})

        return result


def _software_versions() -> dict[str, str]:
    versions = {
        "python": platform.python_version(),
        "numpy": str(np.__version__),
        "scipy": str(scipy.__version__),
        "pydantic": str(pydantic.__version__),
        "terra_scientific": PACKAGE_VERSION,
    }
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        versions["pandas"] = importlib.metadata.version("pandas")
    return versions
