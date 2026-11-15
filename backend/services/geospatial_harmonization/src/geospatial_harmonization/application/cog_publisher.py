"""Cloud Optimized GeoTIFF (COG) publishing pipeline for Project TERRA.

Converts multi-format satellite rasters (GeoTIFF, NetCDF, HDF4, HDF5, Zarr) into
lossless, pyramid-overlaid, internally-tiled Cloud Optimized GeoTIFF assets,
strictly preserving physical scientific values, geotransforms, and nodata semantics.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

import numpy as np
import rasterio
from morecantile import tms
from rasterio.errors import NotGeoreferencedWarning
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

from geospatial_harmonization.application.raster_viz import (
    _evaluate_qa_mask,
    _find_qa_variable,
    _infer_fallback_grid,
    _materialize_asset,
    _read_decoded_sync,
    _select_raster_asset,
    _select_raster_variable,
    _should_convert_kelvin_to_celsius,
    _slice_2d_and_spec,
)
from geospatial_harmonization.domain.exceptions import (
    DomainError,
    IncompatibleDatasetError,
)
from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    SpatialDataset,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.ports import DatasetRepository, StoragePort
from geospatial_harmonization.readers import ReaderRegistry
from geospatial_harmonization.storage.scratch import scratch_base_dir
from geospatial_harmonization.transformations._warp import to_rasterio_affine

logger = logging.getLogger(__name__)


class CogPublishingError(DomainError):
    """Raised when converting or validating a Cloud Optimized GeoTIFF fails."""


@dataclass(frozen=True, slots=True)
class CogPublishResult:
    """Outcome of a COG publishing operation."""

    asset: AssetReference
    dataset_id: UUID
    variable_name: str
    timestamp: str | None
    local_path: Path | None
    storage_key: str
    is_reused: bool
    is_valid_cog: bool


def _safe_token(val: str | None) -> str:
    if not val:
        return "all"
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in str(val).strip())
    return cleaned or "default"


def _deterministic_cog_key(dataset_id: UUID, variable: str, timestamp: str | None) -> str:
    safe_var = _safe_token(variable)
    safe_time = _safe_token(timestamp[:10] if timestamp else None)
    return f"cogs/{dataset_id}/{safe_var}_{safe_time}.tif"


def _is_cog_valid_file(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        is_valid, errors, _ = cog_validate(path, strict=False)
        return bool(is_valid and not errors)
    except Exception:
        return False


def _to_physical_array(
    raw_arr: np.ndarray,
    spec: VariableSpec,
    dataset: SpatialDataset,
    unit_conversion: str | None = None,
) -> tuple[np.ndarray, float]:
    """Convert raw digital numbers to physical scientific values preserving float ranges."""
    arr = np.asarray(raw_arr)
    nodata_val = np.nan

    if np.issubdtype(arr.dtype, np.floating):
        phys = arr.astype(np.float32, copy=True)
        if spec.nodata is not None and not np.isnan(spec.nodata):
            phys[arr == spec.nodata] = np.nan
        if spec.valid_range is not None:
            lo, hi = spec.valid_range
            phys[(phys < lo) | (phys > hi)] = np.nan
    elif np.issubdtype(arr.dtype, np.integer):
        is_nodata = np.zeros(arr.shape, dtype=bool)
        if spec.nodata is not None:
            is_nodata = arr == spec.nodata

        scale = float(spec.scale_factor) if spec.scale_factor is not None else 1.0
        offset = float(spec.add_offset) if spec.add_offset is not None else 0.0

        phys = arr.astype(np.float32) * scale + offset
        phys[is_nodata] = np.nan

        if spec.valid_range is not None:
            lo, hi = spec.valid_range
            phys[(phys < lo) | (phys > hi)] = np.nan
    else:
        phys = arr.astype(np.float32)
        if spec.valid_range is not None:
            lo, hi = spec.valid_range
            phys[(phys < lo) | (phys > hi)] = np.nan

    valid_samples = phys[np.isfinite(phys)]
    sample_f64 = valid_samples.astype(np.float64, copy=False) if valid_samples.size > 0 else None
    if _should_convert_kelvin_to_celsius(spec, dataset, None, unit_conversion, sample_f64):
        phys = np.where(np.isfinite(phys), phys - 273.15, np.nan)
        phys[(phys < -100.0) | (phys > 85.0)] = np.nan

    return phys, nodata_val


def _build_projected_geotiff(
    source_arr: np.ndarray,
    src_grid: GridSpec,
    dst_crs: str,
    target_path: Path,
    nodata: float = np.nan,
) -> None:
    """Write intermediate 2D float32 raster in dst_crs suitable for cog_translate."""
    res_src = src_grid.resolved()
    src_crs = res_src.crs
    src_transform = to_rasterio_affine(res_src)

    if src_crs == dst_crs:
        profile = {
            "driver": "GTiff",
            "height": res_src.height,
            "width": res_src.width,
            "count": 1,
            "dtype": "float32",
            "crs": src_crs,
            "transform": src_transform,
            "nodata": nodata,
        }
        with rasterio.open(target_path, "w", **profile) as dst:
            dst.write(source_arr, 1)
        return

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        dst_crs,
        res_src.width,
        res_src.height,
        left=res_src.bounds.min_x,
        bottom=res_src.bounds.min_y,
        right=res_src.bounds.max_x,
        top=res_src.bounds.max_y,
    )

    dst_arr = np.full((dst_height, dst_width), nodata, dtype=np.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        reproject(
            source=source_arr,
            destination=dst_arr,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=nodata,
            dst_nodata=nodata,
        )

    profile = {
        "driver": "GTiff",
        "height": dst_height,
        "width": dst_width,
        "count": 1,
        "dtype": "float32",
        "crs": dst_crs,
        "transform": dst_transform,
        "nodata": nodata,
    }
    with rasterio.open(target_path, "w", **profile) as dst:
        dst.write(dst_arr, 1)


class CogPublisher:
    """Idempotent publisher converting dataset rasters into validated Cloud Optimized GeoTIFFs."""

    _publish_locks: ClassVar[dict[tuple[int, str], asyncio.Lock]] = {}

    def __init__(
        self,
        storage: StoragePort | None,
        readers: ReaderRegistry,
        datasets: DatasetRepository | None = None,
    ) -> None:
        self._storage = storage
        self._readers = readers
        self._datasets = datasets

    def _lock_for_key(self, cog_key: str) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        cache_key = (loop_id, cog_key)
        lock = self._publish_locks.get(cache_key)
        if lock is None:
            lock = asyncio.Lock()
            self._publish_locks[cache_key] = lock
        return lock

    async def _find_existing_cog(
        self,
        dataset: SpatialDataset,
        var_name: str,
        timestamp: str | None,
        cog_key: str,
    ) -> CogPublishResult | None:
        if self._storage is None:
            return None
        for asset in dataset.assets:
            if (
                asset.data_format == "geotiff"
                and asset.storage_key == cog_key
                and await self._storage.exists(cog_key)
            ):
                local_p = getattr(self._storage, "root_dir", None)
                resolved_p = (local_p / cog_key) if local_p is not None else None
                return CogPublishResult(
                    asset=asset,
                    dataset_id=dataset.dataset_id,
                    variable_name=var_name,
                    timestamp=timestamp,
                    local_path=resolved_p,
                    storage_key=cog_key,
                    is_reused=True,
                    is_valid_cog=True,
                )

        if await self._storage.exists(cog_key):
            local_p = getattr(self._storage, "root_dir", None)
            resolved_p = (local_p / cog_key) if local_p is not None else None
            uri_val = (
                f"s3://{cog_key}"
                if hasattr(self._storage, "_bucket")
                else f"file://{resolved_p or cog_key}"
            )
            existing_asset = AssetReference(
                asset_id=f"cog-{dataset.dataset_id}-{_safe_token(var_name)}",
                uri=uri_val,
                data_format="geotiff",
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                storage_key=cog_key,
                zone="derived",
            )
            return CogPublishResult(
                asset=existing_asset,
                dataset_id=dataset.dataset_id,
                variable_name=var_name,
                timestamp=timestamp,
                local_path=resolved_p,
                storage_key=cog_key,
                is_reused=True,
                is_valid_cog=True,
            )
        return None

    async def get_or_publish_cog(
        self,
        dataset: SpatialDataset,
        *,
        variable: str | None = None,
        timestamp: str | None = None,
        unit_conversion: str | None = None,
        target_crs: str = "EPSG:3857",
    ) -> CogPublishResult:
        """Resolve an existing valid COG or publish a new one idempotently."""
        var_name = variable or next(iter(dataset.variables.keys()))
        cog_key = _deterministic_cog_key(dataset.dataset_id, var_name, timestamp)

        existing = await self._find_existing_cog(dataset, var_name, timestamp, cog_key)
        if existing is not None:
            return existing

        async with self._lock_for_key(cog_key):
            existing = await self._find_existing_cog(dataset, var_name, timestamp, cog_key)
            if existing is not None:
                return existing
            return await self._publish_sync(
                dataset=dataset,
                variable=variable,
                timestamp=timestamp,
                unit_conversion=unit_conversion,
                target_crs=target_crs,
                cog_key=cog_key,
            )

    async def _publish_sync(
        self,
        dataset: SpatialDataset,
        variable: str | None,
        timestamp: str | None,
        unit_conversion: str | None,
        target_crs: str,
        cog_key: str,
    ) -> CogPublishResult:
        asset, step_idx = _select_raster_asset(
            dataset, timestamp=timestamp, variable=variable, prefer_raw=True
        )
        scratch_base = scratch_base_dir()

        with tempfile.TemporaryDirectory(prefix="ghs-cog-pub-", dir=scratch_base) as tmp_dir:
            tmp_root = Path(tmp_dir)
            handle = await _materialize_asset(asset, self._storage, tmp_root)
            try:
                published_local = await asyncio.to_thread(
                    self._convert_to_cog_file,
                    dataset=dataset,
                    asset=asset,
                    asset_path=handle.path,
                    step_idx=step_idx,
                    variable=variable,
                    unit_conversion=unit_conversion,
                    target_crs=target_crs,
                    work_dir=tmp_root,
                )

                # Persist to storage
                new_asset: AssetReference
                if self._storage is not None:
                    new_asset = await self._storage.put_file(
                        cog_key,
                        published_local,
                        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    )
                    # Preserve zone and asset semantics
                    new_asset = AssetReference(
                        asset_id=f"cog-{dataset.dataset_id}-{_safe_token(variable)}",
                        uri=new_asset.uri,
                        data_format="geotiff",
                        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                        checksum_sha256=new_asset.checksum_sha256,
                        size_bytes=new_asset.size_bytes,
                        storage_key=cog_key,
                        zone="derived",
                    )
                else:
                    persisted_copy = scratch_base / f"{dataset.dataset_id}_{Path(cog_key).name}"
                    persisted_copy.write_bytes(published_local.read_bytes())
                    new_asset = AssetReference(
                        asset_id=f"cog-{dataset.dataset_id}-{_safe_token(variable)}",
                        uri=f"file://{persisted_copy}",
                        data_format="geotiff",
                        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                        size_bytes=persisted_copy.stat().st_size,
                        storage_key=cog_key,
                        zone="derived",
                    )
                    published_local = persisted_copy

                # Update dataset in repository if repository available
                if self._datasets is not None:
                    retained = [a for a in dataset.assets if a.storage_key != cog_key]
                    retained.append(new_asset)
                    object.__setattr__(dataset, "assets", tuple(retained))
                    await self._datasets.save(dataset)

                final_local: Path | None = None
                if self._storage is not None and hasattr(self._storage, "root_dir"):
                    final_local = self._storage.root_dir / cog_key
                elif published_local.is_file():
                    final_local = published_local

                return CogPublishResult(
                    asset=new_asset,
                    dataset_id=dataset.dataset_id,
                    variable_name=variable or next(iter(dataset.variables.keys())),
                    timestamp=timestamp,
                    local_path=final_local,
                    storage_key=cog_key,
                    is_reused=False,
                    is_valid_cog=True,
                )
            finally:
                handle.release()

    def _convert_to_cog_file(
        self,
        *,
        dataset: SpatialDataset,
        asset: AssetReference,
        asset_path: Path | None,
        step_idx: int,
        variable: str | None,
        unit_conversion: str | None,
        target_crs: str,
        work_dir: Path,
    ) -> Path:
        decoded = _read_decoded_sync(
            asset=asset,
            asset_path=asset_path,
            readers=self._readers,
            dataset=dataset,
        )
        var_name, spec = _select_raster_variable(decoded, dataset, variable)
        raw_arr = np.asarray(decoded.arrays[var_name])
        slice_arr, render_spec = _slice_2d_and_spec(raw_arr, spec, step_idx)

        src_grid = (
            spec.grid
            or decoded.grid
            or dataset.spatial_metadata.grid
            or _infer_fallback_grid(dataset, slice_arr)
        )
        if src_grid is None:
            raise IncompatibleDatasetError(
                f"Raster variable '{var_name}' lacks spatial grid metadata."
            )

        phys_arr, nodata_val = _to_physical_array(
            slice_arr, render_spec, dataset, unit_conversion=unit_conversion
        )

        # QA mask evaluation
        qa_var = _find_qa_variable(
            decoded, dataset.product, var_name, (phys_arr.shape[0], phys_arr.shape[1])
        )
        if qa_var is not None:
            qa_raw = np.asarray(decoded.arrays[qa_var])
            qa_slice, _ = _slice_2d_and_spec(qa_raw, decoded.variables[qa_var], step_idx)
            try:
                qa_mask = _evaluate_qa_mask(dataset.product, qa_slice, qa_var)
                phys_arr[~qa_mask] = np.nan
            except Exception as exc:
                logger.debug("QA mask evaluation skipped for COG publishing: %s", exc)

        intermediate_tif = work_dir / f"intermediate_{uuid4_hex()}.tif"
        out_cog = work_dir / f"published_{uuid4_hex()}.tif"

        # Reproject to WebMercator EPSG:3857 (or target_crs) for optimal XYZ tile streaming
        _build_projected_geotiff(
            phys_arr,
            src_grid,
            target_crs,
            intermediate_tif,
            nodata=nodata_val,
        )

        # Generate Cloud Optimized GeoTIFF with overview pyramids
        profile = cog_profiles.get("deflate")  # type: ignore[no-untyped-call]
        profile["blocksize"] = 256
        is_continuous = render_spec.semantics.startswith("continuous")
        overview_resampling: Literal["nearest", "bilinear", "cubic", "average"] = (
            "bilinear" if is_continuous else "nearest"
        )

        cog_translate(
            intermediate_tif,
            out_cog,
            profile,
            nodata=nodata_val,
            overview_resampling=overview_resampling,
            tms=tms.get("WebMercatorQuad"),
            forward_band_tags=True,
            quiet=True,
        )

        is_valid, errors, _ = cog_validate(out_cog, strict=False)
        if not is_valid:
            raise CogPublishingError(f"COG validation failed for '{var_name}': {errors}")

        return out_cog


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
