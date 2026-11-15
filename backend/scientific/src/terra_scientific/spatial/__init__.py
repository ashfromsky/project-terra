"""Spatial analysis exports."""

from terra_scientific.spatial.autocorrelation import (
    SpatialAutocorrelationSummary,
    compute_morans_i_and_hotspots,
)
from terra_scientific.spatial.fdr import benjamini_hochberg_fdr
from terra_scientific.spatial.pixel_trends import PixelTrendMaps, compute_chunked_pixel_trends
from terra_scientific.spatial.support_guard import check_spatial_support_compatibility
from terra_scientific.spatial.zonal import (
    compute_grid_weights,
    compute_zonal_statistics,
    extract_area_weighted_series,
)

__all__ = [
    "PixelTrendMaps",
    "SpatialAutocorrelationSummary",
    "benjamini_hochberg_fdr",
    "check_spatial_support_compatibility",
    "compute_chunked_pixel_trends",
    "compute_grid_weights",
    "compute_morans_i_and_hotspots",
    "compute_zonal_statistics",
    "extract_area_weighted_series",
]
