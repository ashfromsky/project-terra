"""Scientific comparison helper computing variable deltas and compatibility notes."""

import math
from dataclasses import dataclass
from typing import Any

from terra.modules.assessments.domain.entities import ScientificAssessment

COMPLETED_STATUSES = frozenset({"completed", "completed_partial"})


@dataclass(frozen=True, slots=True)
class AssessmentComparisonBundle:
    """Computed comparison metrics and provenance warnings for two assessments."""

    primary: ScientificAssessment
    comparison: ScientificAssessment
    shared_variables: list[str]
    primary_only_variables: list[str]
    comparison_only_variables: list[str]
    variable_comparisons: list[dict[str, Any]]
    compatibility_warnings: list[str]
    methodology_notes: list[str]


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f_val = float(value)
    return f_val if math.isfinite(f_val) else None


def _delta(primary_val: float | None, comparison_val: float | None) -> float | None:
    if primary_val is None or comparison_val is None:
        return None
    return primary_val - comparison_val


def _index_trends(result_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_var: dict[str, dict[str, Any]] = {}
    for entry in result_payload.get("trends") or []:
        if not isinstance(entry, dict):
            continue
        var_name = str(entry.get("variable_name") or "")
        if not var_name:
            continue
        if var_name not in by_var or entry.get("variant") == "full_series":
            by_var[var_name] = entry
    return by_var


def _index_resilience(result_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_var: dict[str, dict[str, Any]] = {}
    for entry in result_payload.get("resilience") or []:
        if not isinstance(entry, dict):
            continue
        var_name = str(entry.get("variable_name") or "")
        if var_name:
            by_var[var_name] = entry
    return by_var


def _index_series_means(result_payload: dict[str, Any]) -> dict[str, float | None]:
    means: dict[str, float | None] = {}
    for entry in result_payload.get("temporal_series") or []:
        if not isinstance(entry, dict):
            continue
        var_name = str(entry.get("variable_name") or "")
        if not var_name:
            continue
        raw_vals = entry.get("values") or []
        finite = [
            float(val)
            for val in raw_vals
            if not isinstance(val, bool)
            and isinstance(val, int | float)
            and math.isfinite(float(val))
        ]
        means[var_name] = (sum(finite) / len(finite)) if finite else None
    return means


def _dimension_value(res_entry: dict[str, Any], dimension: str) -> float | None:
    block = res_entry.get(dimension)
    if isinstance(block, dict):
        return _finite_float(block.get("value"))
    return None


def _build_compatibility_warnings(
    primary: ScientificAssessment,
    comparison: ScientificAssessment,
) -> list[str]:
    warnings: list[str] = []
    p_cfg = primary.request_config or {}
    c_cfg = comparison.request_config or {}

    p_cadence = p_cfg.get("target_cadence")
    c_cadence = c_cfg.get("target_cadence")
    if p_cadence != c_cadence:
        warnings.append(
            f"Target temporal cadences differ ({p_cadence} vs {c_cadence}); "
            "compare slope units and variance deltas carefully."
        )

    p_qa = p_cfg.get("qa_policy")
    c_qa = c_cfg.get("qa_policy")
    if p_qa != c_qa:
        warnings.append(
            f"QA screening policies differ ({p_qa} vs {c_qa}); "
            "observation filtering thresholds are not identical."
        )

    p_window = (p_cfg.get("analysis_start"), p_cfg.get("analysis_end"))
    c_window = (c_cfg.get("analysis_start"), c_cfg.get("analysis_end"))
    if p_window != c_window:
        warnings.append(
            f"Analysis windows differ ({p_window[0]}..{p_window[1]} vs "
            f"{c_window[0]}..{c_window[1]})."
        )

    if primary.region_id != comparison.region_id:
        warnings.append("Assessments target two distinct Areas of Interest (spatial comparison).")

    return warnings


def build_assessment_comparison(
    primary: ScientificAssessment,
    comparison: ScientificAssessment,
) -> AssessmentComparisonBundle:
    """Compute aligned variable deltas and methodological compatibility checks."""
    p_res = primary.result_payload or {}
    c_res = comparison.result_payload or {}

    p_trends = _index_trends(p_res)
    c_trends = _index_trends(c_res)
    p_resilience = _index_resilience(p_res)
    c_resilience = _index_resilience(c_res)
    p_means = _index_series_means(p_res)
    c_means = _index_series_means(c_res)

    p_vars = set(p_trends) | set(p_resilience) | set(p_means)
    c_vars = set(c_trends) | set(c_resilience) | set(c_means)

    shared = sorted(p_vars & c_vars)
    p_only = sorted(p_vars - c_vars)
    c_only = sorted(c_vars - p_vars)

    summaries: list[dict[str, Any]] = []
    for var_name in shared:
        pt = p_trends.get(var_name, {})
        ct = c_trends.get(var_name, {})
        pr = p_resilience.get(var_name, {})
        cr = c_resilience.get(var_name, {})

        p_slope = _finite_float(pt.get("sens_slope"))
        c_slope = _finite_float(ct.get("sens_slope"))
        p_res_val = _dimension_value(pr, "resistance")
        c_res_val = _dimension_value(cr, "resistance")
        p_rec_val = _dimension_value(pr, "recovery")
        c_rec_val = _dimension_value(cr, "recovery")
        p_stab_val = _dimension_value(pr, "stability")
        c_stab_val = _dimension_value(cr, "stability")
        p_sens_val = _dimension_value(pr, "sensitivity")
        c_sens_val = _dimension_value(cr, "sensitivity")
        p_mean = p_means.get(var_name)
        c_mean = c_means.get(var_name)

        summaries.append(
            {
                "variable_name": var_name,
                "primary_sens_slope": p_slope,
                "comparison_sens_slope": c_slope,
                "sens_slope_delta": _delta(p_slope, c_slope),
                "slope_unit": pt.get("slope_unit") or ct.get("slope_unit"),
                "primary_direction": pt.get("direction"),
                "comparison_direction": ct.get("direction"),
                "primary_p_value": _finite_float(pt.get("adjusted_p_value") or pt.get("p_value")),
                "comparison_p_value": _finite_float(
                    ct.get("adjusted_p_value") or ct.get("p_value")
                ),
                "primary_resistance": p_res_val,
                "comparison_resistance": c_res_val,
                "resistance_delta": _delta(p_res_val, c_res_val),
                "primary_recovery": p_rec_val,
                "comparison_recovery": c_rec_val,
                "recovery_delta": _delta(p_rec_val, c_rec_val),
                "primary_stability": p_stab_val,
                "comparison_stability": c_stab_val,
                "stability_delta": _delta(p_stab_val, c_stab_val),
                "primary_sensitivity": p_sens_val,
                "comparison_sensitivity": c_sens_val,
                "sensitivity_delta": _delta(p_sens_val, c_sens_val),
                "primary_mean_value": p_mean,
                "comparison_mean_value": c_mean,
                "mean_value_delta": _delta(p_mean, c_mean),
            }
        )

    notes = [
        (
            "Composite TRI remains unavailable_unvalidated; resilience dimensions "
            "(resistance, recovery, stability, sensitivity) are compared separately."
        ),
        "All numeric deltas are reported as (Primary - Comparison).",
    ]
    if p_only or c_only:
        notes.append(
            f"Unmatched variables excluded from delta calculation: "
            f"primary-only={p_only or 'none'}, comparison-only={c_only or 'none'}."
        )

    return AssessmentComparisonBundle(
        primary=primary,
        comparison=comparison,
        shared_variables=shared,
        primary_only_variables=p_only,
        comparison_only_variables=c_only,
        variable_comparisons=summaries,
        compatibility_warnings=_build_compatibility_warnings(primary, comparison),
        methodology_notes=notes,
    )
