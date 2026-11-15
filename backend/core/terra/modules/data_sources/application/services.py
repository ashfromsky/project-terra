"""Use cases coordinating observation discovery, GHS ingestion jobs, and datasets."""

import logging
import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from terra_scientific import evaluate_assessment_readiness
from terra_scientific.adapters.ghs import map_ghs_dataset_payload

from terra.modules.data_sources.application.provisioner import (
    build_readiness_request,
    clamp_window_to_provider_archive,
    compute_adaptive_provision_window,
    dataset_matches_provision_target,
    domain_candidates,
    ensure_utc,
    estimate_max_granules,
    parse_iso_datetime,
)
from terra.modules.data_sources.domain.entities import IngestionOperationRecord
from terra.modules.data_sources.domain.exceptions import (
    DataSourcesAccessDeniedError,
    DataSourcesDomainError,
    DataSourcesNotFoundError,
    DataSourcesValidationError,
)
from terra.modules.data_sources.domain.ports import GhsServiceClient
from terra.modules.data_sources.domain.repositories import IngestionOperationRepository
from terra.modules.regions.domain.repositories import RegionRepository

logger = logging.getLogger("terra.data_sources")

BBoxTuple = tuple[float, float, float, float]


def _validate_bbox(bbox: BBoxTuple) -> BBoxTuple:
    min_lon, min_lat, max_lon, max_lat = bbox
    if not all(math.isfinite(val) for val in bbox):
        raise DataSourcesValidationError("Bounding box coordinates must be finite numbers.")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise DataSourcesValidationError(
            "Bounding box must satisfy min_lon < max_lon and min_lat < max_lat."
        )
    if min_lon < -180.0 or max_lon > 180.0 or min_lat < -90.0 or max_lat > 90.0:
        raise DataSourcesValidationError("Bounding box coordinates must fall within WGS 84 bounds.")
    return (float(min_lon), float(min_lat), float(max_lon), float(max_lat))


def _validate_time_window(start_time: datetime, end_time: datetime) -> None:
    start_cmp = start_time if start_time.tzinfo is not None else start_time.replace(tzinfo=UTC)
    end_cmp = end_time if end_time.tzinfo is not None else end_time.replace(tzinfo=UTC)
    if end_cmp <= start_cmp:
        raise DataSourcesValidationError("endTime must be strictly later than startTime.")


def _extract_variable_names(variables_raw: Any) -> list[str]:
    if isinstance(variables_raw, dict):
        return [str(k) for k in variables_raw]
    if isinstance(variables_raw, list):
        return [str(v) for v in variables_raw]
    return []


def _extract_variable_units(dataset: dict[str, Any]) -> dict[str, str]:
    units: dict[str, str] = {}
    raw_units = dataset.get("units")
    if isinstance(raw_units, dict):
        for key, value in raw_units.items():
            units[str(key)] = str(value)

    variables_raw = dataset.get("variables")
    if isinstance(variables_raw, dict):
        for var_name, meta in variables_raw.items():
            if isinstance(meta, dict) and meta.get("units") and str(var_name) not in units:
                units[str(var_name)] = str(meta["units"])
    return units


def summarize_ghs_dataset(
    dataset: dict[str, Any],
    *,
    region_id: UUID | None = None,
    ingestion_operation_id: UUID | None = None,
    include_series_values: bool = False,
) -> dict[str, Any]:
    """Convert raw GHS DatasetOut JSON into a structured Core summary payload."""
    extensions = dataset.get("extensions") if isinstance(dataset.get("extensions"), dict) else {}
    temporal = (
        dataset.get("temporal_metadata")
        if isinstance(dataset.get("temporal_metadata"), dict)
        else {}
    )
    spatial = (
        dataset.get("spatial_metadata") if isinstance(dataset.get("spatial_metadata"), dict) else {}
    )
    quality = (
        dataset.get("quality_metadata") if isinstance(dataset.get("quality_metadata"), dict) else {}
    )
    provenance = dataset.get("provenance") if isinstance(dataset.get("provenance"), dict) else {}
    ingestion_summary = (
        extensions.get("ingestion_summary")
        if isinstance(extensions.get("ingestion_summary"), dict)
        else {}
    )

    units = _extract_variable_units(dataset)
    variable_names = _extract_variable_names(dataset.get("variables"))

    raw_ts = (
        extensions.get("time_series") if isinstance(extensions.get("time_series"), dict) else {}
    )
    previews: list[dict[str, Any]] = []
    max_series_len = 0
    qa_layers_set: set[str] = set()
    for raw_flag in quality.get("flags_applied") or []:
        if raw_flag:
            qa_layers_set.add(str(raw_flag))
    for raw_ql in quality.get("qa_layers") or []:
        if raw_ql:
            qa_layers_set.add(str(raw_ql))

    for var_name, entry in raw_ts.items():
        if not isinstance(entry, dict):
            continue
        timestamps = [str(ts) for ts in (entry.get("timestamps") or [])]
        raw_values = entry.get("values") or []
        clean_values = [
            float(val) if isinstance(val, int | float) and math.isfinite(float(val)) else None
            for val in raw_values
        ]
        if isinstance(entry.get("qa_layers"), dict):
            qa_layers_set.update(str(k) for k in entry["qa_layers"])
        max_series_len = max(max_series_len, len(timestamps))
        sample_limit = len(timestamps) if include_series_values else 60
        previews.append(
            {
                "variable": str(var_name),
                "count": len(timestamps),
                "start": timestamps[0] if timestamps else None,
                "end": timestamps[-1] if timestamps else None,
                "units": units.get(str(var_name)),
                "timestamps": timestamps[:sample_limit],
                "values": clean_values[:sample_limit],
            }
        )

    obs_count = ingestion_summary.get("observation_count")
    if not isinstance(obs_count, int):
        obs_count = max_series_len

    valid_fraction = quality.get("valid_observation_fraction")
    if not isinstance(valid_fraction, int | float):
        valid_fraction = quality.get("valid_fraction")
    if not isinstance(valid_fraction, int | float):
        missing_frac = quality.get("missing_data_fraction")
        if not isinstance(missing_frac, int | float):
            missing_frac = quality.get("missing_fraction")
        if isinstance(missing_frac, int | float) and math.isfinite(float(missing_frac)):
            valid_fraction = max(0.0, min(1.0, 1.0 - float(missing_frac)))
        else:
            valid_fraction = None

    t_start_dt = parse_iso_datetime(temporal.get("start")) or (
        parse_iso_datetime(previews[0]["start"]) if previews else None
    )
    t_end_dt = parse_iso_datetime(temporal.get("end")) or (
        parse_iso_datetime(previews[0]["end"]) if previews else None
    )
    span_years: float | None = None
    if t_start_dt is not None and t_end_dt is not None and t_end_dt >= t_start_dt:
        span_years = round((t_end_dt - t_start_dt).total_seconds() / (365.25 * 86400.0), 3)

    raw_warnings = ingestion_summary.get("warnings") or quality.get("warnings") or []
    warnings = [str(w) for w in raw_warnings] if isinstance(raw_warnings, list) else []

    nominal_res = spatial.get("nominal_resolution_m")
    return {
        "dataset_id": str(dataset.get("dataset_id", "")),
        "source_id": str(dataset.get("source_id", "")),
        "provider": str(dataset.get("provider", "")),
        "product": str(dataset.get("product", "")),
        "product_version": (
            str(dataset["product_version"]) if dataset.get("product_version") is not None else None
        ),
        "granule_id": (
            str(dataset["granule_id"]) if dataset.get("granule_id") is not None else None
        ),
        "units": units,
        "variables": variable_names,
        "temporal_start": str(temporal["start"]) if temporal.get("start") is not None else None,
        "temporal_end": str(temporal["end"]) if temporal.get("end") is not None else None,
        "temporal_cadence": (
            str(temporal["cadence"]) if temporal.get("cadence") is not None else None
        ),
        "temporal_semantics": (
            str(temporal["semantics"]) if temporal.get("semantics") is not None else None
        ),
        "spatial_crs": str(spatial["crs"]) if spatial.get("crs") is not None else None,
        "nominal_resolution_m": (
            float(nominal_res) if isinstance(nominal_res, int | float) else None
        ),
        "observation_count": int(obs_count),
        "valid_fraction": float(valid_fraction) if valid_fraction is not None else None,
        "qa_policy": str(quality["qa_policy"]) if quality.get("qa_policy") is not None else None,
        "qa_layers_present": sorted(qa_layers_set),
        "span_years": span_years,
        "region_id": str(region_id) if region_id is not None else None,
        "ingestion_operation_id": (
            str(ingestion_operation_id) if ingestion_operation_id is not None else None
        ),
        "warnings": warnings,
        "time_series_previews": previews,
        "provenance": provenance,
        "quality_metadata": quality,
        "spatial_metadata": spatial,
        "temporal_metadata": temporal,
    }


def _build_provider_request_payload(
    *,
    provider: str,
    product: str,
    bbox: BBoxTuple,
    start_time: datetime,
    end_time: datetime,
    max_granules: int,
    variables: list[str],
    run_type: str | None,
    overpass: str | None,
    parameters: list[str],
    community: str | None,
) -> dict[str, Any]:
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()
    bbox_list = [bbox[0], bbox[1], bbox[2], bbox[3]]

    if provider == "modis":
        payload: dict[str, Any] = {
            "product": product,
            "bbox": bbox_list,
            "start_time": start_iso,
            "end_time": end_iso,
            "max_granules": max_granules,
            "data_format": "hdf4",
        }
        if variables:
            payload["variables"] = list(variables)
        return payload

    if provider == "gpm_imerg":
        payload = {
            "product": product,
            "bbox": bbox_list,
            "start_time": start_iso,
            "end_time": end_iso,
            "max_granules": max_granules,
            "run_type": run_type or "Final",
        }
        if variables:
            payload["variables"] = list(variables)
        return payload

    if provider == "smap":
        payload = {
            "product": product,
            "bbox": bbox_list,
            "start_time": start_iso,
            "end_time": end_iso,
            "max_granules": max_granules,
            "overpass": overpass or "AM",
        }
        if variables:
            payload["variables"] = list(variables)
        return payload

    if provider == "nasa_power":
        selected_params = parameters or variables or ["T2M", "PRECTOTCORR", "RH2M"]
        return {
            "product": product,
            "mode": "auto",
            "bbox": bbox_list,
            "start_time": start_iso,
            "end_time": end_iso,
            "community": community or "AG",
            "parameters": list(selected_params),
        }

    payload = {
        "product": product,
        "bbox": bbox_list,
        "start_time": start_iso,
        "end_time": end_iso,
    }
    if variables:
        payload["variables"] = list(variables)
    return payload


class DataSourcesApplicationService:
    """Application orchestrator for satellite discovery, ingestion jobs, and datasets."""

    def __init__(
        self,
        ingestion_repo: IngestionOperationRepository,
        region_repo: RegionRepository,
        ghs_client: GhsServiceClient,
    ) -> None:
        self._ingestion_repo = ingestion_repo
        self._region_repo = region_repo
        self._ghs = ghs_client

    async def _resolve_bbox_and_region_name(
        self,
        owner_id: UUID,
        region_id: UUID | None,
        explicit_bbox: BBoxTuple | None,
    ) -> tuple[BBoxTuple, str | None]:
        if region_id is not None:
            region = await self._region_repo.get_by_id(region_id)
            if region is None:
                raise DataSourcesNotFoundError(f"Region {region_id} was not found.")
            if region.owner_id != owner_id:
                raise DataSourcesAccessDeniedError("Access denied to the requested region.")
            return _validate_bbox(region.metrics.bbox), region.name

        if explicit_bbox is None:
            raise DataSourcesValidationError(
                "Either regionId or an explicit bbox must be provided."
            )
        return _validate_bbox(explicit_bbox), None

    async def list_providers(self) -> list[dict[str, Any]]:
        """Return configured GHS environmental data providers and product capabilities."""
        return await self._ghs.list_providers()

    async def discover_observations(
        self,
        owner_id: UUID,
        *,
        provider: str,
        product: str,
        region_id: UUID | None,
        bbox: BBoxTuple | None,
        start_time: datetime,
        end_time: datetime,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Discover candidate satellite or climate observations for an AOI and time window."""
        _validate_time_window(start_time, end_time)
        resolved_bbox, _ = await self._resolve_bbox_and_region_name(owner_id, region_id, bbox)
        response = await self._ghs.discover_observations(
            {
                "provider": provider,
                "product": product,
                "bbox": list(resolved_bbox),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "limit": limit,
            }
        )
        return {
            "provider": str(response.get("provider", provider)),
            "product": str(response.get("product", product)),
            "count": int(response.get("count", 0)),
            "bbox": resolved_bbox,
            "observations": list(response.get("observations") or []),
        }

    async def start_ingestion(
        self,
        owner_id: UUID,
        *,
        provider: str,
        product: str,
        region_id: UUID | None,
        bbox: BBoxTuple | None,
        start_time: datetime,
        end_time: datetime,
        max_granules: int = 24,
        variables: list[str] | None = None,
        target_cadence: str | None = None,
        target_aggregation: str | None = None,
        run_type: str | None = None,
        overpass: str | None = None,
        parameters: list[str] | None = None,
        community: str | None = None,
        execute_now: bool = False,
        idempotency_key: str | None = None,
    ) -> IngestionOperationRecord:
        """Start a bounded GHS ingestion workflow and persist a tracking record in Core."""
        _validate_time_window(start_time, end_time)
        resolved_bbox, region_name = await self._resolve_bbox_and_region_name(
            owner_id, region_id, bbox
        )
        var_list = list(variables or [])
        param_list = list(parameters or [])

        request_payload = _build_provider_request_payload(
            provider=provider,
            product=product,
            bbox=resolved_bbox,
            start_time=start_time,
            end_time=end_time,
            max_granules=max_granules,
            variables=var_list,
            run_type=run_type,
            overpass=overpass,
            parameters=param_list,
            community=community,
        )

        target_temporal: dict[str, Any] | None = None
        if target_cadence and target_cadence != "native":
            default_agg = "rate_to_depth_sum" if provider == "gpm_imerg" else "mean"
            target_temporal = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "cadence": target_cadence,
                "semantics": "interval",
                "aggregation": (
                    target_aggregation
                    if target_aggregation and target_aggregation != "none"
                    else default_agg
                ),
            }
        elif target_aggregation and target_aggregation != "none":
            target_temporal = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "cadence": "daily",
                "semantics": "interval",
                "aggregation": target_aggregation,
            }

        harmonize_body: dict[str, Any] = {
            "provider": provider,
            "product": product,
            "request_payload": request_payload,
            "variables": var_list,
            "output_format": "geotiff",
        }
        if target_temporal is not None:
            harmonize_body["target_temporal"] = target_temporal
        if idempotency_key:
            harmonize_body["idempotency_key"] = idempotency_key

        operation_id = uuid4()
        request_summary: dict[str, Any] = {
            "region_id": str(region_id) if region_id is not None else None,
            "region_name": region_name,
            "bbox": list(resolved_bbox),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "max_granules": max_granules,
            "variables": var_list,
            "target_cadence": target_cadence or "native",
            "target_aggregation": target_temporal["aggregation"] if target_temporal else "none",
            "run_type": run_type,
            "overpass": overpass,
            "parameters": param_list,
            "execute_now": execute_now,
        }

        if execute_now:
            result = await self._ghs.run_harmonize_sync(harmonize_body)
            dataset = result.get("dataset") if isinstance(result.get("dataset"), dict) else {}
            dataset_id = str(dataset.get("dataset_id") or "") or None
            dataset_summary = (
                summarize_ghs_dataset(
                    dataset,
                    region_id=region_id,
                    ingestion_operation_id=operation_id,
                    include_series_values=True,
                )
                if dataset
                else None
            )
            record = IngestionOperationRecord(
                id=operation_id,
                owner_id=owner_id,
                region_id=region_id,
                ghs_job_id=str(result["job_id"]),
                provider=provider,
                product=product,
                status="succeeded",
                progress_pct=100.0,
                dataset_id=dataset_id,
                request_summary=request_summary,
                dataset_summary=dataset_summary,
            )
            return await self._ingestion_repo.create(record)

        job = await self._ghs.submit_job(harmonize_body)
        status = str(job.get("status", "pending"))
        dataset_id = str(job["dataset_id"]) if job.get("dataset_id") is not None else None
        dataset_summary = None
        if status == "succeeded" and dataset_id is not None:
            try:
                ds_payload = await self._ghs.get_dataset(dataset_id)
                dataset_summary = summarize_ghs_dataset(
                    ds_payload,
                    region_id=region_id,
                    ingestion_operation_id=operation_id,
                    include_series_values=True,
                )
            except DataSourcesDomainError as exc:
                logger.warning("Failed to hydrate dataset %s summary: %s", dataset_id, exc)

        record = IngestionOperationRecord(
            id=operation_id,
            owner_id=owner_id,
            region_id=region_id,
            ghs_job_id=str(job["job_id"]),
            provider=provider,
            product=product,
            status=status,
            progress_pct=float(job.get("progress_pct", 0.0)),
            dataset_id=dataset_id,
            error_message=(
                str(job["error_message"]) if job.get("error_message") is not None else None
            ),
            error_category=(
                str(job["error_category"]) if job.get("error_category") is not None else None
            ),
            request_summary=request_summary,
            dataset_summary=dataset_summary,
        )
        return await self._ingestion_repo.create(record)

    async def _sync_with_ghs(self, record: IngestionOperationRecord) -> IngestionOperationRecord:
        needs_job_poll = record.status in {"pending", "running"}
        needs_dataset_summary = (
            record.status == "succeeded"
            and record.dataset_id is not None
            and record.dataset_summary is None
        )
        if not needs_job_poll and not needs_dataset_summary:
            return record

        changed = False
        if needs_job_poll:
            try:
                job = await self._ghs.get_job(record.ghs_job_id)
            except DataSourcesDomainError as exc:
                logger.warning("Unable to poll GHS job %s: %s", record.ghs_job_id, exc)
                return record

            next_status = str(job.get("status", record.status))
            next_progress = float(job.get("progress_pct", record.progress_pct))
            next_dataset_id = (
                str(job["dataset_id"]) if job.get("dataset_id") is not None else record.dataset_id
            )
            next_err_msg = (
                str(job["error_message"]) if job.get("error_message") is not None else None
            )
            next_err_cat = (
                str(job["error_category"]) if job.get("error_category") is not None else None
            )

            if (
                next_status != record.status
                or next_progress != record.progress_pct
                or next_dataset_id != record.dataset_id
                or next_err_msg != record.error_message
                or next_err_cat != record.error_category
            ):
                record.status = next_status
                record.progress_pct = next_progress
                record.dataset_id = next_dataset_id
                record.error_message = next_err_msg
                record.error_category = next_err_cat
                changed = True

        if (
            record.status == "succeeded"
            and record.dataset_id is not None
            and record.dataset_summary is None
        ):
            try:
                dataset = await self._ghs.get_dataset(record.dataset_id)
                record.dataset_summary = summarize_ghs_dataset(
                    dataset,
                    region_id=record.region_id,
                    ingestion_operation_id=record.id,
                    include_series_values=True,
                )
                changed = True
            except DataSourcesDomainError as exc:
                logger.warning("Unable to load dataset %s summary: %s", record.dataset_id, exc)

        if changed:
            return await self._ingestion_repo.update(record)
        return record

    async def list_ingestions(self, owner_id: UUID) -> list[IngestionOperationRecord]:
        """List ingestion operations owned by the user, syncing active GHS jobs."""
        records = await self._ingestion_repo.list_by_owner(owner_id)
        return [await self._sync_with_ghs(item) for item in records]

    async def get_ingestion(
        self,
        owner_id: UUID,
        operation_id: UUID,
    ) -> IngestionOperationRecord:
        """Retrieve a single ingestion operation after verifying ownership."""
        record = await self._ingestion_repo.get_by_id(operation_id)
        if record is None:
            raise DataSourcesNotFoundError(f"Ingestion operation {operation_id} was not found.")
        if record.owner_id != owner_id:
            raise DataSourcesAccessDeniedError("Access denied to the requested ingestion.")
        return await self._sync_with_ghs(record)

    async def list_datasets(
        self,
        owner_id: UUID,
        *,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List prepared datasets from GHS annotated with matching user ingestion metadata."""
        datasets = await self._ghs.list_datasets(provider=provider, limit=limit)
        operations = await self._ingestion_repo.list_by_owner(owner_id)
        op_by_dataset = {op.dataset_id: op for op in operations if op.dataset_id is not None}
        summaries: list[dict[str, Any]] = []
        for ds in datasets:
            ds_id = str(ds.get("dataset_id", ""))
            matched_op = op_by_dataset.get(ds_id)
            summaries.append(
                summarize_ghs_dataset(
                    ds,
                    region_id=matched_op.region_id if matched_op else None,
                    ingestion_operation_id=matched_op.id if matched_op else None,
                    include_series_values=False,
                )
            )
        return summaries

    async def auto_provision(
        self,
        owner_id: UUID,
        *,
        region_id: UUID | None,
        bbox: BBoxTuple | None,
        analysis_start: datetime,
        analysis_end: datetime,
        target_cadence: str = "monthly",
        baseline_type: str = "out_of_sample",
        reference_start: datetime | None = None,
        reference_end: datetime | None = None,
        min_reference_years: int = 3,
        qa_level: str = "strict",
        existing_dataset_ids: list[str] | None = None,
        desired_domains: list[str] | None = None,
        max_granules_per_product: int = 48,
    ) -> dict[str, Any]:
        """Adaptively expand temporal window, reuse or ingest datasets, and assess readiness."""
        resolved_bbox, _ = await self._resolve_bbox_and_region_name(owner_id, region_id, bbox)
        start_utc = ensure_utc(analysis_start)
        end_utc = ensure_utc(analysis_end)
        _validate_time_window(start_utc, end_utc)

        prov_start, prov_end, window_expanded, expansion_reason = compute_adaptive_provision_window(
            start_utc,
            end_utc,
            baseline_type=baseline_type,
            reference_start=reference_start,
            reference_end=reference_end,
            min_reference_years=min_reference_years,
        )
        span_days = float((prov_end - prov_start).days)

        providers = await self._ghs.list_providers()
        provider_map = {str(p.get("provider", "")): p for p in providers}
        existing_raw = await self._ghs.list_datasets(limit=100)
        operations = await self._ingestion_repo.list_by_owner(owner_id)
        op_by_ds = {op.dataset_id: op for op in operations if op.dataset_id is not None}

        existing_summaries: list[dict[str, Any]] = []
        raw_by_id: dict[str, dict[str, Any]] = {}
        for raw_ds in existing_raw:
            ds_id = str(raw_ds.get("dataset_id", ""))
            if not ds_id:
                continue
            raw_by_id[ds_id] = raw_ds
            matched = op_by_ds.get(ds_id)
            existing_summaries.append(
                summarize_ghs_dataset(
                    raw_ds,
                    region_id=matched.region_id if matched else None,
                    ingestion_operation_id=matched.id if matched else None,
                    include_series_values=False,
                )
            )

        selected_ids: list[str] = []
        seen_ids: set[str] = set()
        for explicit_id in existing_dataset_ids or []:
            cleaned = str(explicit_id).strip()
            if cleaned and cleaned not in seen_ids:
                try:
                    raw_ds = raw_by_id.get(cleaned) or await self._ghs.get_dataset(cleaned)
                except DataSourcesDomainError:
                    continue
                raw_by_id[cleaned] = raw_ds
                seen_ids.add(cleaned)
                selected_ids.append(cleaned)

        steps: list[dict[str, Any]] = []
        domains = list(dict.fromkeys(desired_domains or ["climate", "vegetation"]))
        for domain in domains:
            reused = next(
                (
                    s
                    for s in existing_summaries
                    if dataset_matches_provision_target(
                        s,
                        domain=domain,
                        bbox=resolved_bbox,
                        prov_start=prov_start,
                        prov_end=prov_end,
                        target_cadence=target_cadence,
                    )
                ),
                None,
            )
            if reused is not None:
                ds_id = str(reused["dataset_id"])
                if ds_id not in seen_ids:
                    seen_ids.add(ds_id)
                    selected_ids.append(ds_id)
                steps.append(
                    {
                        "domain": domain,
                        "provider": reused["provider"],
                        "product": reused["product"],
                        "status": "reused",
                        "dataset_id": ds_id,
                        "window_start": prov_start,
                        "window_end": prov_end,
                        "detail": (
                            f"Reused existing prepared dataset '{ds_id}' covering AOI and horizon."
                        ),
                    }
                )
                continue

            candidates = domain_candidates(domain, span_days=span_days)
            if not candidates:
                steps.append(
                    {
                        "domain": domain,
                        "provider": "none",
                        "product": "none",
                        "status": "unavailable",
                        "dataset_id": None,
                        "window_start": prov_start,
                        "window_end": prov_end,
                        "detail": f"No provider mapping registered for domain '{domain}'.",
                    }
                )
                continue

            ingested_for_domain = False
            failure_reasons: list[str] = []
            for idx, cand in enumerate(candidates):
                p_info = provider_map.get(cand.provider)
                if p_info is not None:
                    if not p_info.get("enabled", True):
                        failure_reasons.append(f"{cand.provider} is disabled")
                        continue
                    if p_info.get("auth_required") and not p_info.get("auth_configured", False):
                        failure_reasons.append(
                            f"{cand.provider} ({cand.product}) requires Earthdata credentials"
                        )
                        continue

                clamped = clamp_window_to_provider_archive(cand.provider, prov_start, prov_end)
                if clamped is None:
                    failure_reasons.append(
                        f"{cand.provider} archive misses {prov_start:%Y-%m-%d}..{prov_end:%Y-%m-%d}"
                    )
                    continue
                eff_start, eff_end = clamped

                try:
                    disc = await self._ghs.discover_observations(
                        {
                            "provider": cand.provider,
                            "product": cand.product,
                            "bbox": list(resolved_bbox),
                            "start_time": eff_start.isoformat(),
                            "end_time": eff_end.isoformat(),
                            "limit": 10,
                        }
                    )
                    if int(disc.get("count") or 0) <= 0:
                        failure_reasons.append(
                            f"{cand.product} returned 0 candidate observations for AOI"
                        )
                        continue
                except DataSourcesDomainError as exc:
                    failure_reasons.append(f"{cand.product} discovery failed: {exc}")
                    continue

                max_gran = estimate_max_granules(
                    cand.provider,
                    cand.product,
                    eff_start,
                    eff_end,
                    max_granules_per_product,
                )
                try:
                    op_record = await self.start_ingestion(
                        owner_id,
                        provider=cand.provider,
                        product=cand.product,
                        region_id=region_id,
                        bbox=resolved_bbox,
                        start_time=eff_start,
                        end_time=eff_end,
                        max_granules=max_gran,
                        variables=list(cand.variables),
                        target_cadence=target_cadence,
                        target_aggregation="none",
                        run_type=cand.run_type,
                        overpass=cand.overpass,
                        parameters=list(cand.parameters),
                        community="AG" if cand.provider == "nasa_power" else None,
                        execute_now=True,
                        idempotency_key=None,
                    )
                except DataSourcesDomainError as exc:
                    failure_reasons.append(f"{cand.product} ingestion failed: {exc}")
                    continue

                if op_record.status == "succeeded" and op_record.dataset_id:
                    if op_record.dataset_id not in seen_ids:
                        seen_ids.add(op_record.dataset_id)
                        selected_ids.append(op_record.dataset_id)
                    steps.append(
                        {
                            "domain": domain,
                            "provider": cand.provider,
                            "product": cand.product,
                            "status": "ingested" if idx == 0 else "fallback_ingested",
                            "dataset_id": op_record.dataset_id,
                            "window_start": eff_start,
                            "window_end": eff_end,
                            "detail": (
                                f"Ingested {cand.product} "
                                f"({eff_start:%Y-%m-%d}..{eff_end:%Y-%m-%d}) "
                                f"at '{target_cadence}' cadence."
                            ),
                        }
                    )
                    ingested_for_domain = True
                    break
                failure_reasons.append(
                    op_record.error_message
                    or f"{cand.product} finished with status '{op_record.status}'"
                )

            if not ingested_for_domain:
                last_cand = candidates[0]
                steps.append(
                    {
                        "domain": domain,
                        "provider": last_cand.provider,
                        "product": last_cand.product,
                        "status": "unavailable",
                        "dataset_id": None,
                        "window_start": prov_start,
                        "window_end": prov_end,
                        "detail": "; ".join(failure_reasons)
                        or f"No data available for '{domain}'.",
                    }
                )

        summaries_out: list[dict[str, Any]] = []
        sci_datasets = []
        for ds_id in selected_ids:
            try:
                raw_ds = raw_by_id.get(ds_id) or await self._ghs.get_dataset(ds_id)
            except DataSourcesDomainError:
                continue
            matched = op_by_ds.get(ds_id)
            summaries_out.append(
                summarize_ghs_dataset(
                    raw_ds,
                    region_id=region_id
                    if region_id is not None
                    else (matched.region_id if matched else None),
                    ingestion_operation_id=matched.id if matched else None,
                    include_series_values=False,
                )
            )
            try:
                sci_datasets.append(map_ghs_dataset_payload(raw_ds))
            except Exception as exc:
                logger.warning("Skipping readiness mapping for dataset %s: %s", ds_id, exc)

        sci_req = build_readiness_request(
            analysis_start=start_utc,
            analysis_end=end_utc,
            target_cadence=target_cadence,
            baseline_type=baseline_type,
            reference_start=reference_start,
            reference_end=reference_end,
            min_reference_years=min_reference_years,
            qa_level=qa_level,
        )
        readiness_report = evaluate_assessment_readiness(sci_req, datasets=sci_datasets)

        return {
            "bbox": resolved_bbox,
            "analysis_start": start_utc,
            "analysis_end": end_utc,
            "provision_start": prov_start,
            "provision_end": prov_end,
            "window_expanded": window_expanded,
            "window_expansion_reason": expansion_reason,
            "dataset_ids": selected_ids,
            "datasets": summaries_out,
            "steps": steps,
            "readiness": readiness_report.model_dump(mode="python"),
        }

    async def get_dataset(self, owner_id: UUID, dataset_id: str) -> dict[str, Any]:
        """Retrieve detailed metadata, provenance, and series preview for one GHS dataset."""
        dataset = await self._ghs.get_dataset(dataset_id)
        operations = await self._ingestion_repo.list_by_owner(owner_id)
        matched_op = next((op for op in operations if op.dataset_id == dataset_id), None)
        return summarize_ghs_dataset(
            dataset,
            region_id=matched_op.region_id if matched_op else None,
            ingestion_operation_id=matched_op.id if matched_op else None,
            include_series_values=True,
        )

    async def get_dataset_download_url(
        self,
        owner_id: UUID,
        dataset_id: str,
        *,
        asset_id: str | None = None,
        expires_in: int | None = None,
    ) -> dict[str, Any]:
        """Resolve a dataset asset download descriptor (presigned R2 URL or Core proxy path)."""
        _ = owner_id
        info = await self._ghs.get_dataset_asset_url(
            dataset_id,
            asset_id=asset_id,
            expires_in=expires_in,
        )
        presigned = bool(info.get("presigned"))
        resolved_url = (
            str(info["download_url"])
            if presigned and info.get("download_url")
            else f"/api/v1/data-sources/datasets/{dataset_id}/download"
            + (f"?asset_id={asset_id}" if asset_id else "")
        )
        return {
            "dataset_id": str(info.get("dataset_id", dataset_id)),
            "asset_id": str(info.get("asset_id", asset_id or "")),
            "storage_key": str(info.get("storage_key", "")),
            "filename": str(info.get("filename", f"{dataset_id}.tif")),
            "media_type": str(info.get("media_type", "application/octet-stream")),
            "size_bytes": int(info.get("size_bytes", 0)),
            "checksum_sha256": str(info.get("checksum_sha256", "")),
            "download_url": resolved_url,
            "presigned": presigned,
            "expires_in": info.get("expires_in"),
        }

    async def download_dataset_asset(
        self,
        owner_id: UUID,
        dataset_id: str,
        *,
        asset_id: str | None = None,
    ) -> tuple[bytes, str, str]:
        """Download raw prepared GeoTIFF/JSON/artifact bytes from GHS for an authenticated user."""
        _ = owner_id
        return await self._ghs.download_dataset_asset_content(dataset_id, asset_id=asset_id)
