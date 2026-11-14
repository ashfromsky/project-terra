"""Provider-agnostic TargetGridTransformer implementing the GridTransformer port."""

import tempfile
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

import numpy as np
from pyproj import CRS

from geospatial_harmonization import __version__
from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.models import dataset as dm
from geospatial_harmonization.domain.models import harmonization as hm
from geospatial_harmonization.domain.models.grid import GridSpec
from geospatial_harmonization.domain.models.storage import CompressionPolicy
from geospatial_harmonization.readers import ReaderRegistry, build_default_reader_registry
from geospatial_harmonization.storage.compression import policy_from_settings
from geospatial_harmonization.storage.dedup import compute_file_sha256
from geospatial_harmonization.transformations._warp import (
    WarpedVariable,
    check_upsampling_warning,
    warp_variable,
    write_variable_geotiff,
)


def default_local_asset_resolver(asset: dm.AssetReference) -> Path:
    """Resolve a local path or file:// URI to an existing filesystem path."""
    parsed = urlparse(asset.uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif not parsed.scheme:
        path = Path(asset.uri)
    else:
        raise IncompatibleDatasetError(
            f"Asset '{asset.asset_id}' requires local path or file:// URI, got '{parsed.scheme}'"
        )
    if not path.exists():
        raise IncompatibleDatasetError(f"Asset '{asset.asset_id}' not found on disk: {path}")
    return path


def _resolve_source_grid(
    decoded: dm.DecodedDataset,
    dec_spec: dm.VariableSpec | None,
    ds_spec: dm.VariableSpec,
    dataset: dm.SpatialDataset,
) -> GridSpec:
    candidates = (
        dec_spec.grid if dec_spec is not None else None,
        decoded.grid,
        ds_spec.grid,
        dataset.spatial_metadata.grid,
    )
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.resolved()
        if decoded.crs is not None and CRS.from_user_input(decoded.crs) != CRS.from_user_input(
            resolved.crs
        ):
            raise IncompatibleDatasetError(
                f"Decoded CRS '{decoded.crs}' conflicts with grid CRS '{resolved.crs}'"
            )
        return resolved
    raise IncompatibleDatasetError(
        f"Variable '{ds_spec.name}' has no source GridSpec for spatial transformation"
    )


def _effective_spec(
    ds_spec: dm.VariableSpec, dec_spec: dm.VariableSpec | None, src_grid: GridSpec
) -> dm.VariableSpec:
    fb = dec_spec if dec_spec is not None else ds_spec
    nd = ds_spec.nodata if ds_spec.nodata is not None else fb.nodata
    if ds_spec.semantics in ("categorical", "qa_flag"):
        return replace(ds_spec, nodata=nd, grid=src_grid)
    sc = ds_spec.scale_factor if ds_spec.scale_factor is not None else fb.scale_factor
    off = ds_spec.add_offset if ds_spec.add_offset is not None else fb.add_offset
    return replace(ds_spec, nodata=nd, scale_factor=sc, add_offset=off, grid=src_grid)


def _export_asset(
    run_dir: Path,
    out_id: UUID,
    src_id: UUID,
    var: str,
    method: hm.ResamplingMethod,
    grid: GridSpec,
    warped: WarpedVariable,
    *,
    compression: CompressionPolicy,
    units: str | None = None,
) -> dm.AssetReference:
    out_path = run_dir / f"{var}.tif"
    tags = {
        "GHS_VARIABLE": var,
        "GHS_RESAMPLING": method,
        "GHS_SOURCE_DATASET_ID": str(src_id),
        "GHS_TARGET_CRS": grid.crs,
    }
    write_variable_geotiff(out_path, warped, grid, var, tags, compression=compression, units=units)
    digest, size_bytes = compute_file_sha256(out_path)
    return dm.AssetReference(
        f"{out_id}_{var}",
        out_path.resolve().as_uri(),
        "geotiff",
        "image/tiff",
        digest,
        size_bytes,
    )


class TargetGridTransformer:
    """Universal, provider-agnostic engine aligning datasets onto an explicit target GridSpec."""

    def __init__(
        self,
        output_dir: Path | None = None,
        reader_registry: ReaderRegistry | None = None,
        asset_resolver: Callable[[dm.AssetReference], Path] | None = None,
        compression_policy: CompressionPolicy | None = None,
    ) -> None:
        self._output_dir = output_dir
        self._readers = reader_registry or build_default_reader_registry()
        self._asset_resolver = asset_resolver or default_local_asset_resolver
        self._compression = compression_policy or policy_from_settings()

    def _decode_variables(
        self, dataset: dm.SpatialDataset, selected: tuple[str, ...], target_grid: GridSpec
    ) -> tuple[dict[str, tuple[dm.DecodedDataset, dm.VariableSpec | None]], list[str]]:
        if not dataset.assets:
            raise IncompatibleDatasetError("SpatialDataset has no assets to transform")
        resolved: dict[str, tuple[dm.DecodedDataset, dm.VariableSpec | None]] = {}
        warnings: list[str] = []
        for asset in dataset.assets:
            if len(resolved) == len(selected):
                break
            if asset.data_format in ("json", "csv") and len(dataset.assets) > 1:
                continue
            decoded = self._readers.read_windowed(
                asset,
                self._asset_resolver(asset),
                aoi_bounds=target_grid.bounds,
                aoi_crs=target_grid.crs,
                variables=selected,
                allow_disjoint_fallback=True,
            )
            warnings.extend(w for w in decoded.warnings if w not in warnings)
            for name in selected:
                if name not in resolved and name in decoded.arrays:
                    resolved[name] = (decoded, decoded.variables.get(name))

        missing = [name for name in selected if name not in resolved]
        if missing:
            raise IncompatibleDatasetError(
                f"Requested variable(s) not present in decoded assets: {', '.join(missing)}"
            )
        return resolved, warnings

    def transform(self, request: hm.TargetGridTransformRequest) -> hm.TargetGridTransformResult:
        """Transform selected dataset variables onto request.target_grid without raw mutation."""
        ds = request.dataset
        target_grid = request.target_grid.resolved()
        selected = request.variables or tuple(ds.variables.keys())
        decoded_map, warnings = self._decode_variables(ds, selected, target_grid)

        out_id = uuid4()
        base_dir = self._output_dir or Path(tempfile.mkdtemp(prefix="ghs_transform_"))
        run_dir = base_dir / str(out_id)

        methods: dict[str, hm.ResamplingMethod] = {}
        out_vars: dict[str, dm.VariableSpec] = {}
        out_units: dict[str, str] = {}
        out_assets: list[dm.AssetReference] = []
        valid_sum, pixel_sum = 0, 0

        for name in selected:
            ds_spec = ds.variables[name]
            decoded, dec_spec = decoded_map[name]
            src_grid = _resolve_source_grid(decoded, dec_spec, ds_spec, ds)
            eff = _effective_spec(ds_spec, dec_spec, src_grid)
            method = request.resampling_policy.select_for(
                eff.semantics, request.resampling_overrides.get(name)
            )
            methods[name] = method
            if (up := check_upsampling_warning(src_grid, target_grid)) and up not in warnings:
                warnings.append(up)

            arr = np.asarray(decoded.arrays[name])
            if arr.dtype.kind not in ("i", "u", "f"):
                raise IncompatibleDatasetError(f"Variable '{name}' non-numeric dtype '{arr.dtype}'")
            warped, dims = warp_variable(
                arr,
                eff,
                src_grid,
                target_grid,
                method,
                decoded.coordinates,
                precision=self._compression.precision,
            )
            valid_sum += warped.valid_pixels
            pixel_sum += warped.total_pixels
            unit_label = ds.units.get(name, eff.units)
            out_assets.append(
                _export_asset(
                    run_dir,
                    out_id,
                    ds.dataset_id,
                    name,
                    method,
                    target_grid,
                    warped,
                    compression=self._compression,
                    units=unit_label,
                )
            )
            nd = warped.nodata if isinstance(warped.nodata, (int, float)) else None
            out_vars[name] = replace(
                eff,
                dtype=str(warped.data.dtype),
                dimensions=dims,
                nodata=nd,
                scale_factor=None,
                add_offset=None,
                grid=target_grid,
            )
            out_units[name] = ds.units.get(name, eff.units)

        vf = min(1.0, max(0.0, valid_sum / pixel_sum)) if pixel_sum else 0.0
        errs = () if valid_sum > 0 else ("Transformed output contains zero valid pixels",)
        qc = hm.QualityReport(
            passed=valid_sum > 0,
            valid_fraction=vf,
            nodata_fraction=min(1.0, max(0.0, 1.0 - vf)),
            checks=(
                "spatial_grid_alignment",
                "semantics_resampling_policy",
                "nodata_fraction_accounting",
            ),
            warnings=tuple(warnings),
            errors=errs,
        )
        step = (
            f"target_grid_transform:{target_grid.crs}:"
            f"{target_grid.resolution_x}x{target_grid.resolution_y}"
        )
        prov = (
            replace(
                ds.provenance,
                software_version=__version__,
                processing_steps=(*ds.provenance.processing_steps, step),
            )
            if request.preserve_provenance
            else dm.ProvenanceRecord(
                ds.provider,
                ds.product,
                ds.provenance.product_version,
                datetime.now(UTC),
                __version__,
                processing_steps=(step,),
            )
        )
        ext = {
            **ds.extensions,
            "source_dataset_id": str(ds.dataset_id),
            "target_grid_methods": dict(methods),
        }
        out_ds = dm.SpatialDataset(
            out_id,
            ds.source_id,
            ds.provider,
            ds.product,
            out_vars,
            out_units,
            dm.SpatialMetadata("raster", target_grid.crs, target_grid.bounds, target_grid),
            ds.temporal_metadata,
            replace(ds.quality_metadata, valid_observation_fraction=vf),
            tuple(out_assets),
            prov,
            ext,
        )
        return hm.TargetGridTransformResult(out_ds, target_grid, methods, qc, tuple(warnings))
