"""GeoTIFF / COG AssetReader using rasterio without inventing missing CRS metadata."""

import warnings as py_warnings
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning, RasterioError

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    DataFormat,
    DecodedDataset,
    VariableSpec,
)
from geospatial_harmonization.readers._helpers import (
    as_float,
    build_grid_from_affine,
    canonical_crs_string,
    infer_variable_semantics,
    select_variables,
)
from geospatial_harmonization.readers.registry import AssetDecodeError

_TIFF_PREFIXES = (b"II\x2a\x00", b"MM\x00\x2a", b"II\x2b\x00", b"MM\x00\x2b")


class GeoTIFFReader:
    """Lazy raster decoder for GeoTIFF and Cloud-Optimized GeoTIFF files."""

    @property
    def data_format(self) -> DataFormat:
        return "geotiff"

    def supports(self, asset: AssetReference, header: bytes = b"") -> bool:
        if header:
            return header.startswith(_TIFF_PREFIXES)
        return asset.data_format == "geotiff" or asset.uri.lower().endswith(
            (".tif", ".tiff", ".geotiff")
        )

    def read(
        self, asset: AssetReference, path: Path, variables: tuple[str, ...] | None = None
    ) -> DecodedDataset:
        try:
            with py_warnings.catch_warnings():
                py_warnings.simplefilter("ignore", NotGeoreferencedWarning)
                src = rasterio.open(path)
            with src:
                band_names: dict[str, int] = {}
                for bidx in src.indexes:
                    desc = (src.descriptions[bidx - 1] or "").strip()
                    name = desc if desc and desc not in band_names else f"band_{bidx}"
                    band_names[name] = int(bidx)

                selected = select_variables(band_names.keys(), variables)
                crs_str = canonical_crs_string(src.crs)
                t = src.transform
                grid, warnings = build_grid_from_affine(
                    crs_str, (t.a, t.b, t.c, t.d, t.e, t.f), int(src.width), int(src.height)
                )

                var_specs: dict[str, VariableSpec] = {}
                arrays: dict[str, object] = {}
                extra_warnings = list(warnings)
                for name in selected:
                    bidx = band_names[name]
                    tags = {str(k): v for k, v in src.tags(bidx).items()}
                    semantics = infer_variable_semantics(name, tags)
                    scale = as_float(src.scales[bidx - 1])
                    offset = as_float(src.offsets[bidx - 1])
                    scale = None if scale == 1.0 else scale
                    offset = None if offset == 0.0 else offset
                    if semantics in ("qa_flag", "categorical") and (
                        scale is not None or offset is not None
                    ):
                        extra_warnings.append(f"Dropped scaling on '{name}' ({semantics})")
                        scale, offset = None, None
                    nodata = src.nodatavals[bidx - 1]
                    unit = (src.units[bidx - 1] or "").strip() or "1"
                    arr = np.asarray(src.read(bidx))
                    arrays[name] = arr
                    var_specs[name] = VariableSpec(
                        name=name,
                        units=unit,
                        dtype=str(arr.dtype),
                        dimensions=("y", "x"),
                        semantics=semantics,
                        nodata=nodata if isinstance(nodata, (int, float)) else None,
                        scale_factor=scale,
                        add_offset=offset,
                        grid=grid,
                        attributes=tags,
                    )

                global_tags = {str(k): v for k, v in src.tags().items()}
                return DecodedDataset(
                    asset=asset,
                    data_format="geotiff",
                    variables=var_specs,
                    dimensions={"y": int(src.height), "x": int(src.width)},
                    arrays=arrays,
                    attributes=global_tags,
                    crs=crs_str,
                    grid=grid,
                    nodata=src.nodata if isinstance(src.nodata, (int, float)) else None,
                    warnings=tuple(extra_warnings),
                )
        except RasterioError as exc:
            raise AssetDecodeError(f"Failed to decode GeoTIFF '{path.name}': {exc}") from exc
