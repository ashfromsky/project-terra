"""Scientifically safe, precision-preserving compression across GeoTIFF, NetCDF, Zarr, and HDF."""

import math
import os
import shutil
import uuid
import warnings as py_warnings
from pathlib import Path
from typing import Any, Literal

import h5py
import netCDF4
import numpy as np
import rasterio
import zarr
import zarr.codecs as zarr_codecs
from rasterio.errors import NotGeoreferencedWarning

from geospatial_harmonization.config.settings import Settings, get_settings
from geospatial_harmonization.domain.exceptions import StorageIntegrityError
from geospatial_harmonization.domain.models.dataset import DataFormat
from geospatial_harmonization.domain.models.storage import (
    CompressionPolicy,
    CompressionResult,
    PrecisionPolicy,
)

_LOSSY_CODECS = frozenset({"JPEG", "JPEG2000", "LERC", "LERC_DEFLATE", "LERC_ZSTD", "WEBP"})
_LOSSLESS_TIFF_CODECS = frozenset({"ZSTD", "DEFLATE", "LZW", "PACKBITS", "LZMA"})
_BIGTIFF_THRESHOLD_BYTES = 3_500_000_000


def policy_from_settings(settings: Settings | None = None) -> CompressionPolicy:
    """Construct a CompressionPolicy from service settings."""
    cfg = settings or get_settings()
    return CompressionPolicy(
        enabled=cfg.ghs_storage_compression_enabled,
        raster_codec=cfg.ghs_storage_raster_codec,
        raster_cog_enabled=cfg.ghs_storage_raster_cog_enabled,
        raster_block_size=cfg.ghs_storage_raster_block_size,
        netcdf_complevel=cfg.ghs_storage_netcdf_complevel,
        zarr_codec=cfg.ghs_storage_zarr_codec,
        zarr_target_chunk_bytes=cfg.ghs_storage_zarr_target_chunk_bytes,
        min_recompress_savings_ratio=cfg.ghs_storage_min_recompress_savings_ratio,
        precision=PrecisionPolicy(
            preserve_float64=True,
            preserve_integer_dtype=True,
            allow_lossy_compression=cfg.ghs_storage_allow_lossy_compression,
            allow_quantization=False,
        ),
    )


def validate_precision_transition(
    src_dtype: np.dtype[Any] | str,
    dst_dtype: np.dtype[Any] | str,
    precision: PrecisionPolicy,
    *,
    codec: str | None = None,
    quantized: bool = False,
) -> None:
    """Enforce scientific precision preservation rules and forbid silent lossy downcasting."""
    if quantized and not precision.allow_quantization:
        raise StorageIntegrityError(
            "Quantization of continuous scientific values is forbidden by PrecisionPolicy"
        )
    if (
        codec is not None
        and codec.upper() in _LOSSY_CODECS
        and not precision.allow_lossy_compression
    ):
        raise StorageIntegrityError(
            f"Lossy compression codec '{codec}' is disabled by PrecisionPolicy"
        )
    src_dt = np.dtype(src_dtype)
    dst_dt = np.dtype(dst_dtype)
    if precision.preserve_float64 and src_dt == np.float64 and dst_dt != np.float64:
        raise StorageIntegrityError(
            f"Silent float64 -> {dst_dt.name} precision reduction is forbidden"
        )
    if precision.preserve_integer_dtype and src_dt.kind in ("i", "u"):
        if dst_dt.kind not in ("i", "u"):
            raise StorageIntegrityError(
                f"Silent integer dtype {src_dt.name} -> {dst_dt.name} conversion is forbidden"
            )
        if dst_dt.itemsize < src_dt.itemsize or (src_dt.kind == "i" and dst_dt.kind == "u"):
            raise StorageIntegrityError(
                f"Silent integer precision reduction {src_dt.name} -> {dst_dt.name} is forbidden"
            )


def select_tiff_predictor(dtype: np.dtype[Any] | str) -> int:
    """Choose GDAL TIFF predictor appropriate for float vs integer pixel representation."""
    dt = np.dtype(dtype)
    if dt.kind == "f":
        return 3
    if dt.kind in ("i", "u") and dt.itemsize <= 4:
        return 2
    return 1


def geotiff_creation_options(
    dtype: np.dtype[Any] | str,
    policy: CompressionPolicy,
    *,
    estimated_raw_bytes: int | None = None,
    bigtiff: Literal["IF_SAFER", "YES", "NO"] | None = None,
    cog: bool | None = None,
    codec: Literal["DEFLATE", "ZSTD"] | None = None,
) -> dict[str, Any]:
    """Return validated lossless rasterio GTiff/COG creation options."""
    chosen_codec = codec or policy.raster_codec
    validate_precision_transition(dtype, dtype, policy.precision, codec=chosen_codec)
    use_cog = policy.raster_cog_enabled if cog is None else cog
    resolved_bigtiff: Literal["IF_SAFER", "YES", "NO"]
    if bigtiff is not None:
        resolved_bigtiff = bigtiff
    elif estimated_raw_bytes is not None and estimated_raw_bytes >= _BIGTIFF_THRESHOLD_BYTES:
        resolved_bigtiff = "YES"
    else:
        resolved_bigtiff = "IF_SAFER"

    if not policy.enabled:
        return {"driver": "GTiff", "tiled": True, "bigtiff": resolved_bigtiff}

    predictor = select_tiff_predictor(dtype)
    if use_cog:
        return {
            "driver": "COG",
            "compress": chosen_codec,
            "predictor": predictor,
            "blocksize": policy.raster_block_size,
            "bigtiff": resolved_bigtiff,
            "overview_resampling": "NEAREST",
        }
    return {
        "driver": "GTiff",
        "tiled": True,
        "blockxsize": policy.raster_block_size,
        "blockysize": policy.raster_block_size,
        "compress": chosen_codec,
        "predictor": predictor,
        "bigtiff": resolved_bigtiff,
    }


def compute_balanced_chunks(
    shape: tuple[int, ...],
    itemsize: int,
    target_chunk_bytes: int = 1_048_576,
    *,
    min_chunk_bytes: int = 4_096,
) -> tuple[int, ...]:
    """Compute access-pattern-aware chunk dimensions keeping chunk sizes bounded."""
    if not shape:
        return ()
    dims = [max(1, int(dim)) for dim in shape]
    elem_bytes = max(1, int(itemsize))
    target_elems = max(1, target_chunk_bytes // elem_bytes)
    total_elems = math.prod(dims)
    if total_elems <= target_elems:
        return tuple(dims)

    chunks = list(dims)
    if len(chunks) >= 3:
        for idx in range(len(chunks) - 2):
            chunks[idx] = 1
    while math.prod(chunks) > target_elems:
        reducible = [i for i, c in enumerate(chunks) if c > 1]
        if not reducible:
            break
        axis = max(reducible, key=lambda i: chunks[i])
        chunks[axis] = max(1, math.ceil(chunks[axis] / 2))

    min_elems = max(1, min_chunk_bytes // elem_bytes)
    while math.prod(chunks) < min_elems and math.prod(chunks) < total_elems:
        growable = [i for i, c in enumerate(chunks) if c < dims[i]]
        if not growable:
            break
        axis = max(growable, key=lambda i: dims[i] - chunks[i])
        candidate = min(dims[axis], chunks[axis] * 2)
        if candidate * (math.prod(chunks) // chunks[axis]) > target_elems:
            break
        chunks[axis] = candidate
    return tuple(chunks)


def _dir_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _iter_zarr_arrays(grp: zarr.Group) -> list[zarr.Array[Any]]:
    found: list[zarr.Array[Any]] = []
    for _, member in grp.members():
        if isinstance(member, zarr.Array):
            found.append(member)
        elif isinstance(member, zarr.Group):
            found.extend(_iter_zarr_arrays(member))
    return found


def _tmp_sibling(target: Path, suffix: str) -> Path:
    return target.with_name(f".ghs-tmp-{uuid.uuid4().hex[:10]}{suffix}")


def _should_skip_recompression(
    *,
    already_compressed: bool,
    original_bytes: int,
    candidate_bytes: int,
    min_savings_ratio: float,
    force: bool,
) -> str | None:
    if force or original_bytes <= 0:
        return None
    savings_ratio = (original_bytes - candidate_bytes) / original_bytes
    if already_compressed and savings_ratio < min_savings_ratio:
        return "already_compressed_below_savings_threshold"
    if not already_compressed and candidate_bytes >= original_bytes:
        return "compression_did_not_reduce_size"
    return None


def _build_zarr_codec(policy: CompressionPolicy) -> Any:
    if policy.zarr_codec == "gzip":
        return zarr_codecs.GzipCodec(level=policy.netcdf_complevel)
    if policy.zarr_codec == "blosc":
        return zarr_codecs.BloscCodec(cname="zstd", clevel=min(9, policy.netcdf_complevel))
    return zarr_codecs.ZstdCodec(level=min(9, policy.netcdf_complevel))


def _copy_netcdf_group(
    src_grp: Any,
    dst_grp: Any,
    *,
    complevel: int,
    target_chunk_bytes: int,
    precision: PrecisionPolicy,
    preserved_keys: set[str],
) -> None:
    for attr_name in src_grp.ncattrs():
        dst_grp.setncattr(attr_name, src_grp.getncattr(attr_name))
        preserved_keys.add(f"global:{attr_name}")
    for dim_name, dim in src_grp.dimensions.items():
        dst_grp.createDimension(dim_name, None if dim.isunlimited() else len(dim))
    for var_name, src_var in src_grp.variables.items():
        validate_precision_transition(src_var.dtype, src_var.dtype, precision)
        var_attrs = {k: src_var.getncattr(k) for k in src_var.ncattrs() if k != "_FillValue"}
        fill_val = src_var.getncattr("_FillValue") if "_FillValue" in src_var.ncattrs() else None
        is_compressable = (
            src_var.ndim >= 1 and src_var.dtype.kind not in ("O", "U", "S") and src_var.size > 1
        )
        chunks: tuple[int, ...] | None = None
        if is_compressable:
            chunks = compute_balanced_chunks(
                tuple(int(s) for s in src_var.shape),
                int(src_var.dtype.itemsize),
                target_chunk_bytes=target_chunk_bytes,
            )
        dst_var = dst_grp.createVariable(
            var_name,
            src_var.dtype,
            src_var.dimensions,
            zlib=is_compressable,
            complevel=complevel if is_compressable else 0,
            shuffle=is_compressable,
            chunksizes=chunks,
            fill_value=fill_val,
        )
        for k, v in var_attrs.items():
            dst_var.setncattr(k, v)
            preserved_keys.add(k)
        if fill_val is not None:
            preserved_keys.add("_FillValue")
        dst_var[:] = src_var[:]
    for sub_name, sub_grp in src_grp.groups.items():
        _copy_netcdf_group(
            sub_grp,
            dst_grp.createGroup(sub_name),
            complevel=complevel,
            target_chunk_bytes=target_chunk_bytes,
            precision=precision,
            preserved_keys=preserved_keys,
        )


def _copy_h5_group(
    src_grp: Any,
    dst_grp: Any,
    *,
    complevel: int,
    target_chunk_bytes: int,
    precision: PrecisionPolicy,
    preserved_keys: set[str],
) -> None:
    for k, v in src_grp.attrs.items():
        dst_grp.attrs[k] = v
        preserved_keys.add(str(k))
    for name, item in src_grp.items():
        if isinstance(item, h5py.Group):
            sub = dst_grp.create_group(name)
            _copy_h5_group(
                item,
                sub,
                complevel=complevel,
                target_chunk_bytes=target_chunk_bytes,
                precision=precision,
                preserved_keys=preserved_keys,
            )
        elif isinstance(item, h5py.Dataset):
            validate_precision_transition(item.dtype, item.dtype, precision)
            is_compressable = item.ndim >= 1 and item.dtype.kind not in ("O", "U", "S")
            if is_compressable and item.size > 1:
                chunks = compute_balanced_chunks(
                    tuple(int(s) for s in item.shape),
                    int(item.dtype.itemsize),
                    target_chunk_bytes=target_chunk_bytes,
                )
                ds = dst_grp.create_dataset(
                    name,
                    data=item[()],
                    dtype=item.dtype,
                    chunks=chunks,
                    compression="gzip",
                    compression_opts=complevel,
                    shuffle=True,
                )
            else:
                ds = dst_grp.create_dataset(name, data=item[()], dtype=item.dtype)
            for k, v in item.attrs.items():
                ds.attrs[k] = v
                preserved_keys.add(str(k))


def _copy_zarr_group(
    src_grp: zarr.Group,
    dst_grp: zarr.Group,
    *,
    codec: Any,
    target_chunk_bytes: int,
    precision: PrecisionPolicy,
    preserved_keys: set[str],
) -> None:
    dst_grp.attrs.update(dict(src_grp.attrs))
    for key in src_grp.attrs:
        preserved_keys.add(str(key))
    for name, member in src_grp.members():
        if isinstance(member, zarr.Group):
            sub = dst_grp.create_group(name)
            _copy_zarr_group(
                member,
                sub,
                codec=codec,
                target_chunk_bytes=target_chunk_bytes,
                precision=precision,
                preserved_keys=preserved_keys,
            )
        elif isinstance(member, zarr.Array):
            validate_precision_transition(member.dtype, member.dtype, precision)
            raw_shape = tuple(int(s) for s in member.shape)
            chunks = compute_balanced_chunks(
                raw_shape, int(member.dtype.itemsize), target_chunk_bytes=target_chunk_bytes
            )
            dim_names = getattr(member.metadata, "dimension_names", None)
            compressors: Any = codec if member.ndim >= 1 and member.size > 1 else None
            dst_arr = dst_grp.create_array(
                name,
                shape=raw_shape,
                chunks=chunks or raw_shape,
                dtype=member.dtype,
                fill_value=member.fill_value,
                dimension_names=dim_names,
                compressors=compressors,
                attributes=dict(member.attrs),
            )
            dst_arr[:] = member[:]
            for attr_key in member.attrs:
                preserved_keys.add(str(attr_key))


class DataCompressionManager:
    """Lossless, precision-preserving compression manager across raster and array formats."""

    def __init__(
        self,
        settings: Settings | None = None,
        policy: CompressionPolicy | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._policy = policy or policy_from_settings(self._settings)

    @property
    def policy(self) -> CompressionPolicy:
        return self._policy

    def validate_precision_transition(
        self,
        src_dtype: np.dtype[Any] | str,
        dst_dtype: np.dtype[Any] | str,
        *,
        codec: str | None = None,
        quantized: bool = False,
    ) -> None:
        validate_precision_transition(
            src_dtype, dst_dtype, self._policy.precision, codec=codec, quantized=quantized
        )

    def preserve_raw_source(self, src_path: Path, *, data_format: DataFormat) -> CompressionResult:
        """Preserve original raw assets (e.g. HDF4) untouched while recording asset metrics."""
        orig_bytes = _dir_size_bytes(src_path) if src_path.exists() else 0
        return CompressionResult(
            output_path=str(src_path),
            data_format=data_format,
            codec="none",
            original_bytes=orig_bytes,
            compressed_bytes=orig_bytes,
            saved_bytes=0,
            skipped_reason="preserve_raw_source_immutable",
        )

    def optimize_geotiff(
        self,
        src_path: Path,
        dst_path: Path | None = None,
        *,
        cog: bool | None = None,
        codec: Literal["DEFLATE", "ZSTD"] | None = None,
        bigtiff: Literal["IF_SAFER", "YES", "NO"] | None = None,
        force: bool = False,
    ) -> CompressionResult:
        """Compress a GeoTIFF/COG losslessly while preserving exact dtypes, scaling, and tags."""
        target = dst_path or src_path
        orig_bytes = src_path.stat().st_size
        chosen_codec = codec or self._policy.raster_codec
        self.validate_precision_transition("float64", "float64", codec=chosen_codec)

        with py_warnings.catch_warnings():
            py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
            src = rasterio.open(src_path)

        with src:
            existing_comp = src.compression.name.upper() if src.compression else None
            already_compressed = existing_comp in _LOSSLESS_TIFF_CODECS
            primary_dtype = np.dtype(src.dtypes[0])
            self.validate_precision_transition(primary_dtype, primary_dtype, codec=chosen_codec)

            if not self._policy.enabled:
                if target != src_path:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, target)
                return CompressionResult(
                    output_path=str(target),
                    data_format="geotiff",
                    codec=existing_comp or "none",
                    original_bytes=orig_bytes,
                    compressed_bytes=orig_bytes,
                    saved_bytes=0,
                    skipped_reason="compression_disabled",
                )

            raw_est = int(src.height) * int(src.width) * int(src.count) * primary_dtype.itemsize
            creation_opts = geotiff_creation_options(
                primary_dtype,
                self._policy,
                estimated_raw_bytes=raw_est,
                bigtiff=bigtiff,
                cog=cog,
                codec=chosen_codec,
            )
            tmp_out = _tmp_sibling(target, ".tif")
            target.parent.mkdir(parents=True, exist_ok=True)
            preserved_keys: set[str] = set()
            try:
                with rasterio.open(
                    tmp_out,
                    "w",
                    height=int(src.height),
                    width=int(src.width),
                    count=int(src.count),
                    dtype=str(primary_dtype),
                    crs=src.crs,
                    transform=src.transform,
                    nodata=src.nodatavals[0] if src.nodatavals else src.nodata,
                    **creation_opts,
                ) as dst:
                    for bidx in src.indexes:
                        dst.write(src.read(bidx), bidx)
                        if src.descriptions[bidx - 1]:
                            dst.set_band_description(bidx, src.descriptions[bidx - 1])
                        b_tags = src.tags(bidx)
                        if b_tags:
                            dst.update_tags(bidx, **b_tags)
                            preserved_keys.update(str(k) for k in b_tags)
                    dst.scales = src.scales
                    dst.offsets = src.offsets
                    dst.units = src.units
                    if any(u for u in src.units):
                        preserved_keys.add("units")
                    if any(s != 1.0 for s in src.scales):
                        preserved_keys.add("scale_factor")
                    if any(o != 0.0 for o in src.offsets):
                        preserved_keys.add("add_offset")
                    g_tags = src.tags()
                    if g_tags:
                        dst.update_tags(**g_tags)
                        preserved_keys.update(str(k) for k in g_tags)

                comp_bytes = tmp_out.stat().st_size
                skip_reason = _should_skip_recompression(
                    already_compressed=already_compressed,
                    original_bytes=orig_bytes,
                    candidate_bytes=comp_bytes,
                    min_savings_ratio=self._policy.min_recompress_savings_ratio,
                    force=force,
                )
                if skip_reason is not None:
                    tmp_out.unlink(missing_ok=True)
                    if target != src_path:
                        shutil.copy2(src_path, target)
                    return CompressionResult(
                        output_path=str(target),
                        data_format="geotiff",
                        codec=existing_comp or "none",
                        original_bytes=orig_bytes,
                        compressed_bytes=orig_bytes,
                        saved_bytes=0,
                        skipped_reason=skip_reason,
                        metadata_preserved=tuple(sorted(preserved_keys)),
                    )
                os.replace(tmp_out, target)
                return CompressionResult(
                    output_path=str(target),
                    data_format="geotiff",
                    codec=chosen_codec,
                    original_bytes=orig_bytes,
                    compressed_bytes=comp_bytes,
                    saved_bytes=max(0, orig_bytes - comp_bytes),
                    metadata_preserved=tuple(sorted(preserved_keys)),
                )
            except BaseException:
                tmp_out.unlink(missing_ok=True)
                raise

    def optimize_netcdf(
        self,
        src_path: Path,
        dst_path: Path | None = None,
        *,
        complevel: int | None = None,
        force: bool = False,
    ) -> CompressionResult:
        """Apply lossless zlib + shuffle + balanced chunking while keeping coordinates & attrs."""
        target = dst_path or src_path
        orig_bytes = src_path.stat().st_size
        lvl = complevel if complevel is not None else self._policy.netcdf_complevel
        if not self._policy.enabled:
            if target != src_path:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, target)
            return CompressionResult(
                output_path=str(target),
                data_format="netcdf",
                codec="none",
                original_bytes=orig_bytes,
                compressed_bytes=orig_bytes,
                saved_bytes=0,
                skipped_reason="compression_disabled",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = _tmp_sibling(target, ".nc")
        preserved_keys: set[str] = set()
        already_compressed = True
        try:
            with netCDF4.Dataset(src_path, "r") as src_ds:
                multi_vars = [v for v in src_ds.variables.values() if v.ndim >= 1 and v.size > 1]
                already_compressed = bool(multi_vars) and all(
                    bool((v.filters() or {}).get("zlib", False)) for v in multi_vars
                )
                target_format: Literal["NETCDF4", "NETCDF4_CLASSIC"] = (
                    "NETCDF4_CLASSIC" if src_ds.data_model == "NETCDF4_CLASSIC" else "NETCDF4"
                )
                with netCDF4.Dataset(tmp_out, "w", format=target_format) as dst_ds:
                    _copy_netcdf_group(
                        src_ds,
                        dst_ds,
                        complevel=lvl,
                        target_chunk_bytes=self._policy.zarr_target_chunk_bytes,
                        precision=self._policy.precision,
                        preserved_keys=preserved_keys,
                    )

            comp_bytes = tmp_out.stat().st_size
            skip_reason = _should_skip_recompression(
                already_compressed=already_compressed,
                original_bytes=orig_bytes,
                candidate_bytes=comp_bytes,
                min_savings_ratio=self._policy.min_recompress_savings_ratio,
                force=force,
            )
            if skip_reason is not None:
                tmp_out.unlink(missing_ok=True)
                if target != src_path:
                    shutil.copy2(src_path, target)
                return CompressionResult(
                    output_path=str(target),
                    data_format="netcdf",
                    codec="zlib" if already_compressed else "none",
                    original_bytes=orig_bytes,
                    compressed_bytes=orig_bytes,
                    saved_bytes=0,
                    skipped_reason=skip_reason,
                    metadata_preserved=tuple(sorted(preserved_keys)),
                )
            os.replace(tmp_out, target)
            return CompressionResult(
                output_path=str(target),
                data_format="netcdf",
                codec=f"zlib_level_{lvl}",
                original_bytes=orig_bytes,
                compressed_bytes=comp_bytes,
                saved_bytes=max(0, orig_bytes - comp_bytes),
                metadata_preserved=tuple(sorted(preserved_keys)),
            )
        except BaseException:
            tmp_out.unlink(missing_ok=True)
            raise

    def optimize_zarr(
        self,
        src_path: Path,
        dst_path: Path | None = None,
        *,
        force: bool = False,
    ) -> CompressionResult:
        """Rechunk and losslessly compress a Zarr v3 store preserving attrs and dtypes."""
        target = dst_path or src_path
        orig_bytes = _dir_size_bytes(src_path)
        if not self._policy.enabled:
            if target != src_path:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(src_path, target)
            return CompressionResult(
                output_path=str(target),
                data_format="zarr",
                codec="none",
                original_bytes=orig_bytes,
                compressed_bytes=orig_bytes,
                saved_bytes=0,
                skipped_reason="compression_disabled",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = _tmp_sibling(target, ".zarr")
        preserved_keys: set[str] = set()
        codec_obj = _build_zarr_codec(self._policy)
        try:
            src_root = zarr.open_group(src_path, mode="r")
            arrays = _iter_zarr_arrays(src_root)
            already_compressed = bool(arrays) and all(
                bool(arr.compressors) for arr in arrays if arr.size > 1
            )
            dst_root = zarr.open_group(tmp_out, mode="w")
            _copy_zarr_group(
                src_root,
                dst_root,
                codec=codec_obj,
                target_chunk_bytes=self._policy.zarr_target_chunk_bytes,
                precision=self._policy.precision,
                preserved_keys=preserved_keys,
            )

            comp_bytes = _dir_size_bytes(tmp_out)
            skip_reason = _should_skip_recompression(
                already_compressed=already_compressed,
                original_bytes=orig_bytes,
                candidate_bytes=comp_bytes,
                min_savings_ratio=self._policy.min_recompress_savings_ratio,
                force=force,
            )
            if skip_reason is not None:
                shutil.rmtree(tmp_out, ignore_errors=True)
                if target != src_path:
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(src_path, target)
                return CompressionResult(
                    output_path=str(target),
                    data_format="zarr",
                    codec=self._policy.zarr_codec if already_compressed else "none",
                    original_bytes=orig_bytes,
                    compressed_bytes=orig_bytes,
                    saved_bytes=0,
                    skipped_reason=skip_reason,
                    metadata_preserved=tuple(sorted(preserved_keys)),
                )

            if target.exists():
                shutil.rmtree(target)
            os.replace(tmp_out, target)
            return CompressionResult(
                output_path=str(target),
                data_format="zarr",
                codec=self._policy.zarr_codec,
                original_bytes=orig_bytes,
                compressed_bytes=comp_bytes,
                saved_bytes=max(0, orig_bytes - comp_bytes),
                metadata_preserved=tuple(sorted(preserved_keys)),
            )
        except BaseException:
            shutil.rmtree(tmp_out, ignore_errors=True)
            raise

    def optimize_hdf5(
        self,
        src_path: Path,
        dst_path: Path | None = None,
        *,
        complevel: int | None = None,
        force: bool = False,
    ) -> CompressionResult:
        """Compress derived HDF5 datasets losslessly with gzip + shuffle without changing attrs."""
        target = dst_path or src_path
        orig_bytes = src_path.stat().st_size
        lvl = complevel if complevel is not None else self._policy.netcdf_complevel
        if not self._policy.enabled:
            if target != src_path:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, target)
            return CompressionResult(
                output_path=str(target),
                data_format="hdf5",
                codec="none",
                original_bytes=orig_bytes,
                compressed_bytes=orig_bytes,
                saved_bytes=0,
                skipped_reason="compression_disabled",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = _tmp_sibling(target, ".h5")
        preserved_keys: set[str] = set()
        try:
            already_compressed = True
            found_ds = False
            with h5py.File(src_path, "r") as src_f:

                def _check_comp(_name: str, obj: Any) -> None:
                    nonlocal already_compressed, found_ds
                    if isinstance(obj, h5py.Dataset) and obj.ndim >= 1 and obj.size > 1:
                        found_ds = True
                        if obj.compression is None:
                            already_compressed = False

                src_f.visititems(_check_comp)
                if not found_ds:
                    already_compressed = False
                with h5py.File(tmp_out, "w") as dst_f:
                    _copy_h5_group(
                        src_f,
                        dst_f,
                        complevel=lvl,
                        target_chunk_bytes=self._policy.zarr_target_chunk_bytes,
                        precision=self._policy.precision,
                        preserved_keys=preserved_keys,
                    )

            comp_bytes = tmp_out.stat().st_size
            skip_reason = _should_skip_recompression(
                already_compressed=already_compressed,
                original_bytes=orig_bytes,
                candidate_bytes=comp_bytes,
                min_savings_ratio=self._policy.min_recompress_savings_ratio,
                force=force,
            )
            if skip_reason is not None:
                tmp_out.unlink(missing_ok=True)
                if target != src_path:
                    shutil.copy2(src_path, target)
                return CompressionResult(
                    output_path=str(target),
                    data_format="hdf5",
                    codec="gzip" if already_compressed else "none",
                    original_bytes=orig_bytes,
                    compressed_bytes=orig_bytes,
                    saved_bytes=0,
                    skipped_reason=skip_reason,
                    metadata_preserved=tuple(sorted(preserved_keys)),
                )

            os.replace(tmp_out, target)
            return CompressionResult(
                output_path=str(target),
                data_format="hdf5",
                codec=f"gzip_level_{lvl}",
                original_bytes=orig_bytes,
                compressed_bytes=comp_bytes,
                saved_bytes=max(0, orig_bytes - comp_bytes),
                metadata_preserved=tuple(sorted(preserved_keys)),
            )
        except BaseException:
            tmp_out.unlink(missing_ok=True)
            raise
