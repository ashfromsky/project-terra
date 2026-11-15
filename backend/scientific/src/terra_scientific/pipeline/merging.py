"""Deterministic merging and deduplication for compatible multi-granule datasets."""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import numpy as np

from terra_scientific.domain.models.dataset import (
    ObservationSeries,
    ScientificDataset,
    ScientificGridStack,
    VariableMetadata,
)


def _compat_key(ds: ScientificDataset) -> tuple[object, ...]:
    res = (
        round(ds.spatial_support.nominal_resolution_m, 3)
        if ds.spatial_support.nominal_resolution_m is not None
        else None
    )
    return (
        ds.source_id,
        ds.product.strip().upper(),
        ds.product_version.strip(),
        ds.temporal_metadata.cadence,
        ds.temporal_metadata.composite_days,
        ds.temporal_metadata.calendar.strip().lower(),
        ds.spatial_support.crs.strip().upper(),
        res,
        ds.run_type or "",
        ds.overpass_mode.value if ds.overpass_mode is not None else "",
    )


def _var_signature(meta: VariableMetadata) -> tuple[str, str, str]:
    return (
        meta.canonical_name.strip().lower(),
        meta.units.strip(),
        meta.semantic_kind.value,
    )


def _deduplicate_preserve_order(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _merge_series_group(
    series_items: list[tuple[ScientificDataset, ObservationSeries]],
    var_name: str,
) -> tuple[ObservationSeries, list[str]]:
    notes: list[str] = []
    # Collect (ts, retrieval_ts, ds_id, val, qa_map, overpass_tag, int_start, int_end)
    records: list[
        tuple[
            datetime,
            datetime,
            str,
            float | None,
            dict[str, int | None],
            str | None,
            datetime | None,
            datetime | None,
        ]
    ] = []
    all_qa_keys: list[str] = []
    has_overpass = any(s.overpass_tags is not None for _, s in series_items)
    has_starts = any(s.interval_starts is not None for _, s in series_items)
    has_ends = any(s.interval_ends is not None for _, s in series_items)

    for ds, s in series_items:
        for k in s.qa_layers:
            if k not in all_qa_keys:
                all_qa_keys.append(k)
        ret_ts = ds.retrieval_timestamp or datetime.min.replace(tzinfo=UTC)
        for idx, ts in enumerate(s.timestamps):
            qa_row = {k: s.qa_layers[k][idx] for k in s.qa_layers}
            ov = s.overpass_tags[idx] if s.overpass_tags is not None else None
            istart = s.interval_starts[idx] if s.interval_starts is not None else None
            iend = s.interval_ends[idx] if s.interval_ends is not None else None
            records.append((ts, ret_ts, ds.dataset_id, s.values[idx], qa_row, ov, istart, iend))

    # Group by exact timestamp to deduplicate deterministically
    type _TsRecord = tuple[
        datetime,
        str,
        float | None,
        dict[str, int | None],
        str | None,
        datetime | None,
        datetime | None,
    ]
    by_ts: dict[datetime, list[_TsRecord]] = defaultdict(list)
    for ts, ret_ts, ds_id, val, qa_row, ov, istart, iend in records:
        by_ts[ts].append((ret_ts, ds_id, val, qa_row, ov, istart, iend))

    dedup_count = 0
    chosen: list[
        tuple[
            datetime,
            float | None,
            dict[str, int | None],
            str | None,
            datetime | None,
            datetime | None,
        ]
    ] = []
    for ts in sorted(by_ts.keys()):
        candidates = by_ts[ts]
        if len(candidates) > 1:
            dedup_count += len(candidates) - 1
        # Prefer finite values; break ties by (retrieval_timestamp, dataset_id) descending
        candidates_sorted = sorted(
            candidates,
            key=lambda item: (
                1 if (item[2] is not None and math.isfinite(item[2])) else 0,
                item[0],
                item[1],
            ),
            reverse=True,
        )
        best = candidates_sorted[0]
        chosen.append((ts, best[2], best[3], best[4], best[5], best[6]))

    if dedup_count > 0:
        notes.append(
            f"{var_name}: deduplicated {dedup_count} overlapping timestamp(s) across "
            f"{len(series_items)} compatible datasets."
        )

    merged_ts = [c[0] for c in chosen]
    merged_vals = [c[1] for c in chosen]
    merged_qa: dict[str, list[int | None]] = {k: [c[2].get(k) for c in chosen] for k in all_qa_keys}
    merged_overpass = [c[3] or "" for c in chosen] if has_overpass else None
    merged_starts = [c[4] or c[0] for c in chosen] if has_starts else None
    merged_ends = [c[5] or c[0] for c in chosen] if has_ends else None

    return (
        ObservationSeries(
            timestamps=merged_ts,
            values=merged_vals,
            interval_starts=merged_starts,
            interval_ends=merged_ends,
            qa_layers=merged_qa,
            overpass_tags=merged_overpass,
            metadata=series_items[0][1].metadata,
        ),
        notes,
    )


def _merge_stack_group(
    stack_items: list[tuple[ScientificDataset, ScientificGridStack]],
    target_dataset_id: str,
    var_name: str,
) -> tuple[ScientificGridStack | None, list[str]]:
    if not stack_items:
        return None, []
    first_shape = stack_items[0][1].data.shape[1:]
    first_crs = stack_items[0][1].spatial_support.crs.strip().upper()
    for _, st in stack_items[1:]:
        if st.data.shape[1:] != first_shape or st.spatial_support.crs.strip().upper() != first_crs:
            return None, [
                f"{var_name}: skipped grid stack merge due to differing spatial grid shape/CRS "
                f"({st.data.shape[1:]} vs {first_shape})."
            ]

    # Collect per-time-slice records across stacks
    slices: dict[datetime, tuple[datetime, str, np.ndarray, dict[str, np.ndarray]]] = {}
    dedup_count = 0
    all_qa_keys = sorted({k for _, st in stack_items for k in st.qa_arrays})

    for ds, st in stack_items:
        ret_ts = ds.retrieval_timestamp or datetime.min.replace(tzinfo=UTC)
        for idx, ts in enumerate(st.timestamps):
            qa_slice = {
                k: st.qa_arrays[k][idx]
                if k in st.qa_arrays
                else np.full(first_shape, -999999, dtype=np.int64)
                for k in all_qa_keys
            }
            data_slice = st.data[idx]
            if ts in slices:
                dedup_count += 1
                prev_ret, prev_id, prev_data, _ = slices[ts]
                prev_valid = int(np.isfinite(prev_data).sum())
                curr_valid = int(np.isfinite(data_slice).sum())
                if (curr_valid, ret_ts, ds.dataset_id) > (prev_valid, prev_ret, prev_id):
                    slices[ts] = (ret_ts, ds.dataset_id, data_slice, qa_slice)
            else:
                slices[ts] = (ret_ts, ds.dataset_id, data_slice, qa_slice)

    sorted_ts = sorted(slices.keys())
    merged_data = np.stack([slices[ts][2] for ts in sorted_ts], axis=0)
    merged_qa = {k: np.stack([slices[ts][3][k] for ts in sorted_ts], axis=0) for k in all_qa_keys}
    base_stack = stack_items[0][1]
    notes: list[str] = []
    if dedup_count > 0:
        notes.append(f"{var_name}: deduplicated {dedup_count} overlapping grid timestamp(s).")

    return (
        ScientificGridStack(
            dataset_id=target_dataset_id,
            source_id=base_stack.source_id,
            product=base_stack.product,
            product_version=base_stack.product_version,
            variable=base_stack.variable,
            spatial_support=base_stack.spatial_support,
            timestamps=sorted_ts,
            data=merged_data,
            qa_arrays=merged_qa,
            cell_areas_m2=base_stack.cell_areas_m2,
            aoi_mask=base_stack.aoi_mask,
            metadata=dict(base_stack.metadata),
        ),
        notes,
    )


def merge_compatible_datasets(
    datasets: Sequence[ScientificDataset],
    grid_stacks: Mapping[str, ScientificGridStack] | None = None,
) -> tuple[list[ScientificDataset], dict[str, ScientificGridStack], list[str]]:
    """Merge compatible multi-granule datasets deterministically while preserving provenance."""
    raw_stacks = dict(grid_stacks or {})
    if len(datasets) <= 1:
        return list(datasets), raw_stacks, []

    groups: dict[tuple[object, ...], list[ScientificDataset]] = defaultdict(list)
    group_order: list[tuple[object, ...]] = []
    for ds in datasets:
        key = _compat_key(ds)
        if key not in groups:
            group_order.append(key)
        groups[key].append(ds)

    merged_datasets: list[ScientificDataset] = []
    merged_stacks: dict[str, ScientificGridStack] = {}
    warnings: list[str] = []

    for key in group_order:
        group = groups[key]
        if len(group) == 1:
            ds = group[0]
            merged_datasets.append(ds)
            for var_name in set(ds.variables) | set(ds.series) | set(ds.raster_refs):
                k = f"{ds.dataset_id}:{var_name}"
                if k in raw_stacks:
                    merged_stacks[k] = raw_stacks[k]
                elif var_name in raw_stacks:
                    merged_stacks[var_name] = raw_stacks[var_name]
            continue

        # Sort group deterministically by temporal start then dataset_id
        ordered = sorted(
            group,
            key=lambda d: (
                d.temporal_metadata.start or datetime.min.replace(tzinfo=UTC),
                d.dataset_id,
            ),
        )

        # Verify variable signature compatibility across group members
        base_ds = ordered[0]
        base_sigs = {v: _var_signature(meta) for v, meta in base_ds.variables.items()}
        compatible: list[ScientificDataset] = [base_ds]
        incompatible: list[ScientificDataset] = []

        for candidate in ordered[1:]:
            conflict = False
            for v_name, c_meta in candidate.variables.items():
                if v_name in base_sigs and _var_signature(c_meta) != base_sigs[v_name]:
                    conflict = True
                    warnings.append(
                        f"Skipped merging dataset '{candidate.dataset_id}' into "
                        f"'{base_ds.dataset_id}' due to incompatible variable '{v_name}' metadata "
                        f"({_var_signature(c_meta)} vs {base_sigs[v_name]})."
                    )
                    break
            if conflict:
                incompatible.append(candidate)
            else:
                compatible.append(candidate)

        if len(compatible) == 1:
            merged_datasets.extend(ordered)
            for ds in ordered:
                for var_name in set(ds.variables) | set(ds.series) | set(ds.raster_refs):
                    k = f"{ds.dataset_id}:{var_name}"
                    if k in raw_stacks:
                        merged_stacks[k] = raw_stacks[k]
            continue

        merged_vars: dict[str, VariableMetadata] = {}
        merged_qa_layers: dict[str, str] = {}
        merged_series: dict[str, ObservationSeries] = {}
        merged_raster_refs: dict[str, str] = {}
        all_granules: list[str] = []
        all_notes: list[str] = []
        all_limitations: list[str] = []
        all_timestamps: list[datetime] = []

        for ds in compatible:
            for v_name, v_meta in ds.variables.items():
                merged_vars.setdefault(v_name, v_meta)
            for qk, qv in ds.qa_layers.items():
                merged_qa_layers.setdefault(qk, qv)
            for r_k, r_v in ds.raster_refs.items():
                merged_raster_refs.setdefault(r_k, r_v)
            all_granules.extend(ds.granule_ids)
            all_notes.extend(ds.provenance_notes)
            all_limitations.extend(ds.limitations)
            if ds.temporal_metadata.start is not None:
                all_timestamps.append(ds.temporal_metadata.start)
            if ds.temporal_metadata.end is not None:
                all_timestamps.append(ds.temporal_metadata.end)

        for var_name in merged_vars:
            s_items = [(ds, ds.series[var_name]) for ds in compatible if var_name in ds.series]
            if s_items:
                m_series, s_notes = _merge_series_group(s_items, var_name)
                merged_series[var_name] = m_series
                all_notes.extend(s_notes)
                all_timestamps.extend(m_series.timestamps)

            st_items = []
            for ds in compatible:
                st = raw_stacks.get(f"{ds.dataset_id}:{var_name}") or raw_stacks.get(var_name)
                if st is not None:
                    st_items.append((ds, st))
            if st_items:
                m_stack, st_notes = _merge_stack_group(st_items, base_ds.dataset_id, var_name)
                if m_stack is not None:
                    merged_stacks[f"{base_ds.dataset_id}:{var_name}"] = m_stack
                    all_timestamps.extend(m_stack.timestamps)
                else:
                    warnings.extend(st_notes)
                    for ds, st in st_items:
                        merged_stacks[f"{ds.dataset_id}:{var_name}"] = st

        merged_ids = [ds.dataset_id for ds in compatible]
        all_notes.append(
            f"Merged {len(compatible)} compatible granules/datasets into '{base_ds.dataset_id}': "
            f"{', '.join(merged_ids)}."
        )

        t_meta = base_ds.temporal_metadata.model_copy(
            update={
                "start": min(all_timestamps) if all_timestamps else base_ds.temporal_metadata.start,
                "end": max(all_timestamps) if all_timestamps else base_ds.temporal_metadata.end,
            }
        )

        merged_ds = base_ds.model_copy(
            update={
                "granule_ids": tuple(_deduplicate_preserve_order(all_granules)),
                "temporal_metadata": t_meta,
                "variables": merged_vars,
                "qa_layers": merged_qa_layers,
                "series": merged_series,
                "raster_refs": merged_raster_refs,
                "provenance_notes": _deduplicate_preserve_order(all_notes),
                "limitations": _deduplicate_preserve_order(all_limitations),
            }
        )
        merged_datasets.append(merged_ds)

        for inc_ds in incompatible:
            merged_datasets.append(inc_ds)
            for var_name in set(inc_ds.variables) | set(inc_ds.series) | set(inc_ds.raster_refs):
                k = f"{inc_ds.dataset_id}:{var_name}"
                if k in raw_stacks:
                    merged_stacks[k] = raw_stacks[k]

    return merged_datasets, merged_stacks, warnings
