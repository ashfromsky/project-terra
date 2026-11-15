"""Persist derived and resilience spatial raster artifacts into GHS storage and catalog."""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models.dataset import (
    ProvenanceRecord,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.storage import AssetReferenceLink
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.domain.ports import DatasetRepository, StoragePort
from geospatial_harmonization.storage.dedup import ContentDeduplicationService, compute_file_sha256
from geospatial_harmonization.storage.quota import StorageQuotaManager
from geospatial_harmonization.storage.scratch import scratch_base_dir
from geospatial_harmonization.storage.zones import StorageZoneManager
from geospatial_harmonization.transformations._warp import WarpedVariable, write_variable_geotiff


def _rasterize_aoi_scalar(
    bbox: tuple[float, float, float, float],
    scalar_value: float,
    aoi_geojson: dict[str, Any] | None,
    width: int = 64,
    height: int = 64,
) -> NDArray[np.float32]:
    min_lon, min_lat, max_lon, max_lat = bbox
    arr = np.full((height, width), np.nan, dtype=np.float32)
    if aoi_geojson is None:
        arr[:, :] = np.float32(scalar_value)
        return arr

    transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)
    inside = geometry_mask(
        [aoi_geojson], out_shape=(height, width), transform=transform, invert=True
    )
    arr[inside] = np.float32(scalar_value)
    return arr


async def persist_derived_raster(
    *,
    datasets: DatasetRepository,
    storage: StoragePort,
    product: str,
    variable_name: str,
    units: str,
    bbox_wgs84: tuple[float, float, float, float],
    scope: Literal["grid", "aoi"],
    values_2d: list[list[float | None]] | None = None,
    scalar_value: float | None = None,
    aoi_geojson: dict[str, Any] | None = None,
    temporal_start: datetime | None = None,
    temporal_end: datetime | None = None,
    timestamps: list[str] | None = None,
    time_series_values: list[float | None] | None = None,
    source_dataset_ids: list[str] | None = None,
    qa_policy: str | None = None,
    method_version: str = "1.0.0",
    quota: StorageQuotaManager | None = None,
    dedup: ContentDeduplicationService | None = None,
    zones: StorageZoneManager | None = None,
) -> SpatialDataset:
    """Write a derived/resilience 2D float32 GeoTIFF into derived/ storage and register it."""
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    if not (-180.0 <= min_lon < max_lon <= 180.0 and -90.0 <= min_lat < max_lat <= 90.0):
        raise IncompatibleDatasetError(f"Invalid WGS 84 bbox for derived raster: {bbox_wgs84}")

    if values_2d is not None:
        if not values_2d or not values_2d[0]:
            raise IncompatibleDatasetError("values_2d cannot be empty")
        arr = np.array(
            [[np.nan if v is None else float(v) for v in row] for row in values_2d],
            dtype=np.float32,
        )
    elif scalar_value is not None:
        arr = _rasterize_aoi_scalar(bbox_wgs84, float(scalar_value), aoi_geojson)
    else:
        raise IncompatibleDatasetError("Either values_2d or scalar_value must be provided")

    height, width = arr.shape
    bounds = SpatialBounds(min_lon, min_lat, max_lon, max_lat)
    res_x = (max_lon - min_lon) / float(width)
    res_y = (max_lat - min_lat) / float(height)
    grid = GridSpec(
        crs="EPSG:4326",
        resolution_x=res_x,
        resolution_y=res_y,
        resolution_unit="degree",
        bounds=bounds,
        width=width,
        height=height,
    ).resolved()

    var_spec = VariableSpec(
        name=variable_name,
        units=units,
        dtype="float32",
        dimensions=("y", "x"),
        semantics="continuous_intensive",
        nodata=None,
        grid=grid,
    )

    dataset_id = uuid4()
    storage_key = f"derived/{product}/{dataset_id}.tif"
    valid_pixels = int(np.count_nonzero(np.isfinite(arr)))
    warped = WarpedVariable(
        data=arr,
        nodata=np.nan,
        valid_pixels=valid_pixels,
        total_pixels=int(arr.size),
    )

    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="ghs-derived-", dir=scratch_base_dir()) as tmp_dir:
        out_path = Path(tmp_dir) / f"{dataset_id}.tif"
        write_variable_geotiff(
            out_path,
            warped,
            grid,
            variable_name,
            tags={
                "product": product,
                "scope": scope,
                "method_version": method_version,
            },
            units=units,
        )
        if dedup is not None and quota is not None and zones is not None:
            digest, file_size = compute_file_sha256(out_path)
            storage_key = zones.derived_key(
                str(dataset_id),
                f"{dataset_id}.tif",
                product=product,
                content_sha256=digest,
            )
            async with quota.reservation_scope(
                estimated_bytes=file_size,
                zone="derived",
                operation="derived_raster",
                job_id=str(dataset_id),
                now=now,
            ) as res_handle:
                link = AssetReferenceLink(
                    object_key=storage_key,
                    ref_kind="dataset",
                    ref_owner_id=str(dataset_id),
                    asset_id=storage_key,
                    provider="terra_scientific",
                    product=product,
                    created_at=now,
                    metadata={"scope": scope, "method_version": method_version},
                )
                dedup_res = await dedup.store_or_deduplicate_file(
                    source_path=out_path,
                    zone="derived",
                    object_key=storage_key,
                    ref=link,
                    media_type="image/tiff",
                    data_format="geotiff",
                    now=now,
                )
                res_handle.actual_bytes = (
                    0 if dedup_res.deduplicated else dedup_res.record.size_bytes
                )
                asset = replace(
                    dedup_res.asset_reference,
                    asset_id=dedup_res.record.object_key,
                    storage_key=dedup_res.record.object_key,
                    data_format="geotiff",
                    zone="derived",
                )
        else:
            raw_bytes = out_path.read_bytes()
            stored_ref = await storage.put_bytes(
                storage_key,
                raw_bytes,
                media_type="image/tiff",
            )
            asset = replace(
                stored_ref,
                asset_id=storage_key,
                storage_key=storage_key,
                data_format="geotiff",
                zone="derived",
            )

    t_start = temporal_start or now
    t_end = temporal_end or t_start
    coverage = float(valid_pixels / max(arr.size, 1))

    extensions: dict[str, object] = {
        "scope": scope,
        "method_version": method_version,
        "source_dataset_ids": list(source_dataset_ids or []),
    }
    if qa_policy:
        extensions["qa_policy"] = qa_policy
    if timestamps and time_series_values:
        extensions["time_series"] = {
            variable_name: {
                "timestamps": list(timestamps),
                "values": list(time_series_values),
            }
        }

    dataset = SpatialDataset(
        dataset_id=dataset_id,
        source_id="terra_scientific",
        provider="terra_scientific",
        product=product,
        product_version="v0.1",
        variables={variable_name: var_spec},
        units={variable_name: units},
        spatial_metadata=SpatialMetadata(
            representation="raster",
            crs="EPSG:4326",
            bounds=bounds,
            grid=grid,
        ),
        temporal_metadata=TemporalSpec(
            start=t_start,
            end=t_end,
            cadence="multi_year" if scope == "aoi" else "monthly",
            semantics="climatology" if t_start < t_end else "instantaneous",
        ),
        assets=(asset,),
        provenance=ProvenanceRecord(
            provider="terra_scientific",
            product=product,
            product_version="v0.1",
            retrieved_at=now,
            software_version=method_version,
        ),
        quality_metadata=QualityMetadata(
            qa_policy=qa_policy or "TERRA Scientific Core derived product",
            valid_observation_fraction=1.0,
            spatial_coverage_fraction=coverage,
        ),
        extensions=extensions,
    )
    await datasets.save(dataset)
    return dataset
