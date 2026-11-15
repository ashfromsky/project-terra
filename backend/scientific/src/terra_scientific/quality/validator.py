"""Scientific input screening: fill masking, single scaling, physical bounds, and QA."""

import numpy as np
from numpy.typing import NDArray

from terra_scientific.domain.enums import DataSourceId, OverpassMode, QaPolicyLevel
from terra_scientific.domain.exceptions import ScientificInputError
from terra_scientific.domain.models.dataset import (
    ScientificDataset,
    ScientificGridStack,
    VariableMetadata,
)
from terra_scientific.domain.models.quality import QaPolicySpec, QualitySummary
from terra_scientific.quality.qa_policies import evaluate_source_qa
from terra_scientific.sources.catalog import assert_quantitative_source_allowed, get_qa_policy


def _screen_array(
    raw_values: NDArray[np.float64],
    qa_arrays: dict[str, NDArray[np.int64]],
    source_id: DataSourceId,
    product: str,
    var_meta: VariableMetadata,
    qa_level: QaPolicyLevel,
    *,
    overpass_tags: list[str] | None = None,
    overpass_mode: OverpassMode = OverpassMode.AM_ONLY,
    allow_imerg_early_late: bool = False,
    run_type: str | None = None,
    pqi_array: NDArray[np.float64] | None = None,
) -> tuple[NDArray[np.float64], QualitySummary]:
    assert_quantitative_source_allowed(source_id, product)

    warnings: list[str] = []
    if source_id == DataSourceId.GPM_IMERG and run_type is not None:
        rt_norm = run_type.strip().lower()
        if "mixed" in rt_norm:
            raise ScientificInputError(
                "Mixed IMERG Early/Late/Final runs cannot be combined silently.",
                code="imerg_mixed_run_prohibited",
            )
        if rt_norm != "final":
            if not allow_imerg_early_late:
                raise ScientificInputError(
                    f"GPM IMERG '{run_type}' run is unsuitable for retrospective Final baseline "
                    "unless allow_imerg_early_late=True.",
                    code="imerg_non_final_run",
                )
            warnings.append(
                f"IMERG '{run_type}' near-real-time run used explicitly instead of Final run."
            )

    policy: QaPolicySpec | None = None
    try:
        policy = get_qa_policy(source_id, product, qa_level)
    except ScientificInputError:
        policy = None

    values = np.array(raw_values, dtype=np.float64, copy=True)
    missing_mask = ~np.isfinite(values)
    for fill in var_meta.fill_values:
        missing_mask |= np.isclose(values, fill, rtol=1e-6, atol=1e-9)

    values[missing_mask] = np.nan
    missing_count = int(np.sum(missing_mask))

    if not var_meta.is_scaled and (var_meta.scale_factor != 1.0 or var_meta.add_offset != 0.0):
        valid_to_scale = ~np.isnan(values)
        values[valid_to_scale] = (
            values[valid_to_scale] * var_meta.scale_factor + var_meta.add_offset
        )

    range_mask = np.zeros(values.shape, dtype=bool)
    if var_meta.valid_range is not None:
        low, high = var_meta.valid_range
        present = ~np.isnan(values)
        range_mask = present & ((values < low) | (values > high))
        values[range_mask] = np.nan
    out_of_range_count = int(np.sum(range_mask))

    qa_valid_mask, qa_dist = evaluate_source_qa(source_id, qa_arrays, qa_level)
    if not qa_arrays and source_id in {
        DataSourceId.MODIS_MOD13Q1,
        DataSourceId.MODIS_MOD11A2,
        DataSourceId.SMAP_SPL3SMP_E,
    }:
        warnings.append(
            "No QA flag layers provided; screening relied on fill values and physical bounds only."
        )

    filtered_by_qa = 0
    if qa_valid_mask is not None:
        currently_present = ~np.isnan(values)
        qa_rejected = currently_present & ~qa_valid_mask
        filtered_by_qa += int(np.sum(qa_rejected))
        values[qa_rejected] = np.nan

    if (
        source_id == DataSourceId.GPM_IMERG
        and pqi_array is not None
        and policy is not None
        and "min_pqi" in policy.bitmask_rules
    ):
        min_pqi = float(str(policy.bitmask_rules["min_pqi"]))
        present = ~np.isnan(values)
        pqi_bad = present & (~np.isfinite(pqi_array) | (pqi_array < min_pqi))
        filtered_by_qa += int(np.sum(pqi_bad))
        values[pqi_bad] = np.nan

    if source_id == DataSourceId.SMAP_SPL3SMP_E and overpass_tags is not None and values.ndim == 1:
        upper_tags = [t.strip().upper() for t in overpass_tags]
        distinct_tags = {t for t in upper_tags if t in {"AM", "PM"}}
        if overpass_mode == OverpassMode.AM_ONLY:
            mask_overpass = np.array([t != "AM" for t in upper_tags], dtype=bool)
        elif overpass_mode == OverpassMode.PM_ONLY:
            mask_overpass = np.array([t != "PM" for t in upper_tags], dtype=bool)
        elif overpass_mode == OverpassMode.AM_PM_SEPARATE and len(distinct_tags) > 1:
            raise ScientificInputError(
                "Mixed SMAP AM and PM overpass tags cannot be pooled in AM_PM_SEPARATE mode.",
                code="smap_mixed_overpass",
            )
        else:
            mask_overpass = np.zeros(values.shape, dtype=bool)
            if len(distinct_tags) > 1:
                warnings.append("SMAP AM and PM overpasses explicitly merged.")
        present = ~np.isnan(values)
        overpass_rejected = present & mask_overpass
        filtered_by_qa += int(np.sum(overpass_rejected))
        values[overpass_rejected] = np.nan

    total = int(values.size)
    valid_count = int(np.sum(~np.isnan(values)))
    valid_fraction = valid_count / total if total > 0 else 0.0
    min_cov = policy.min_coverage_fraction if policy is not None else 0.5
    passed = valid_fraction >= min_cov and valid_count > 0
    if not passed:
        warnings.append(
            f"Valid fraction {valid_fraction:.3f} below policy threshold {min_cov:.3f}."
        )

    summary = QualitySummary(
        total_observations=total,
        valid_observations=valid_count,
        filtered_by_qa=filtered_by_qa,
        missing_or_fill=missing_count,
        out_of_physical_range=out_of_range_count,
        valid_fraction=valid_fraction,
        qa_distribution=qa_dist,
        qa_policy_applied=policy.policy_id if policy else f"generic_{qa_level.value}",
        warnings=warnings,
        passed_sufficiency=passed,
    )
    return values, summary


def screen_dataset_variable(
    dataset: ScientificDataset,
    variable_name: str,
    qa_level: QaPolicyLevel = QaPolicyLevel.STANDARD,
    *,
    overpass_mode: OverpassMode | None = None,
    allow_imerg_early_late: bool = False,
) -> tuple[NDArray[np.float64], QualitySummary]:
    """Validate, scale once, and QA-filter a 1D ObservationSeries on ScientificDataset."""
    series = dataset.series.get(variable_name)
    if series is None:
        raise ScientificInputError(
            f"Dataset '{dataset.dataset_id}' has no 1D observation series for '{variable_name}'."
        )
    _, vals, qa_np = series.to_numpy()
    effective_overpass = (
        overpass_mode
        if overpass_mode is not None
        else (dataset.overpass_mode or OverpassMode.AM_ONLY)
    )
    return _screen_array(
        vals,
        qa_np,
        dataset.source_id,
        dataset.product,
        series.metadata,
        qa_level,
        overpass_tags=series.overpass_tags,
        overpass_mode=effective_overpass,
        allow_imerg_early_late=allow_imerg_early_late,
        run_type=dataset.run_type,
    )


def screen_grid_stack(
    stack: ScientificGridStack,
    qa_level: QaPolicyLevel = QaPolicyLevel.STANDARD,
    *,
    allow_imerg_early_late: bool = False,
    run_type: str | None = None,
) -> tuple[ScientificGridStack, QualitySummary]:
    """Validate, mask fill, scale once, and QA-filter a 3D ScientificGridStack."""
    screened_arr, summary = _screen_array(
        stack.data,
        stack.qa_arrays,
        stack.source_id,
        stack.product,
        stack.variable,
        qa_level,
        allow_imerg_early_late=allow_imerg_early_late,
        run_type=run_type,
    )
    if stack.aoi_mask is not None:
        screened_arr[:, ~stack.aoi_mask] = np.nan

    scaled_var = stack.variable.model_copy(update={"is_scaled": True})
    new_stack = ScientificGridStack(
        dataset_id=stack.dataset_id,
        source_id=stack.source_id,
        product=stack.product,
        product_version=stack.product_version,
        variable=scaled_var,
        spatial_support=stack.spatial_support,
        timestamps=list(stack.timestamps),
        data=screened_arr,
        qa_arrays=stack.qa_arrays,
        cell_areas_m2=stack.cell_areas_m2,
        aoi_mask=stack.aoi_mask,
        metadata=dict(stack.metadata),
    )
    return new_stack, summary
