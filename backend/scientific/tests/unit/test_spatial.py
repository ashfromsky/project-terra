"""Unit tests for spatial statistics, chunked pixel trends, BH FDR, and Moran's I / Gi*."""

from datetime import UTC, datetime

import numpy as np
import pytest

from terra_scientific.domain.enums import DataSourceId, VariableSemanticKind
from terra_scientific.domain.models.dataset import (
    ScientificGridStack,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.request import SpatialConfig, TrendConfig
from terra_scientific.sources.catalog import MODIS_SINUSOIDAL_WKT
from terra_scientific.spatial.autocorrelation import compute_morans_i_and_hotspots
from terra_scientific.spatial.fdr import benjamini_hochberg_fdr
from terra_scientific.spatial.pixel_trends import compute_chunked_pixel_trends
from terra_scientific.spatial.zonal import compute_zonal_statistics


def test_area_weighted_zonal_statistics_masks_invalid_and_weights_correctly() -> None:
    arr = np.array([[[0.2, 0.8], [np.nan, 0.5]]], dtype=np.float64)
    areas = np.array([[100.0, 300.0], [100.0, 100.0]], dtype=np.float64)
    aoi_mask = np.array([[True, True], [True, False]], dtype=bool)
    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    stack = ScientificGridStack(
        dataset_id="s-1",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        variable=meta,
        spatial_support=SpatialSupport(crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0),
        timestamps=[datetime(2020, 1, 1, tzinfo=UTC)],
        data=arr,
        cell_areas_m2=areas,
        aoi_mask=aoi_mask,
    )
    stats = compute_zonal_statistics(stack)
    # Valid AOI pixels: (0.2 area 100, 0.8 area 300) => weighted mean = (20 + 240)/400 = 0.65
    # Unweighted mean = 0.5; total AOI pixels = 3, valid = 2 => coverage = 2/3
    assert stats.area_weighted_mean == pytest.approx(0.65)
    assert stats.unweighted_mean == pytest.approx(0.5)
    assert stats.valid_pixel_count == 2
    assert stats.total_pixel_count == 3
    assert stats.coverage_fraction == pytest.approx(2.0 / 3.0)


def test_benjamini_hochberg_fdr_preserves_nans_and_controls_false_discoveries() -> None:
    pvals = np.array([0.001, 0.008, 0.039, 0.041, 0.80, np.nan], dtype=np.float64)
    qvals, sig = benjamini_hochberg_fdr(pvals, alpha=0.05)
    assert np.isnan(qvals[-1])
    assert not sig[-1]
    assert sig[0] and sig[1]
    assert not sig[4]
    # Adjusted q-values must remain monotone non-decreasing when sorted by raw p
    finite_idx = np.argsort(pvals[:-1])
    assert np.all(np.diff(qvals[finite_idx]) >= -1e-12)


def test_chunked_pixel_trends_recovers_slope_map_and_fdr_fractions() -> None:
    ts = [datetime(2010 + i, 1, 1, tzinfo=UTC) for i in range(12)]
    data = np.zeros((12, 4, 4), dtype=np.float64)
    years = np.arange(12, dtype=np.float64)[:, None, None]
    # Top 2 rows have strong positive trend +0.02/yr; bottom 2 rows constant/flat
    data[:, :2, :] = 0.4 + 0.02 * years
    data[:, 2:, :] = 0.5
    data[:, 3, 3] = np.nan

    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    stack = ScientificGridStack(
        dataset_id="s-pix",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        variable=meta,
        spatial_support=SpatialSupport(crs=MODIS_SINUSOIDAL_WKT, nominal_resolution_m=250.0),
        timestamps=ts,
        data=data,
    )
    res = compute_chunked_pixel_trends(
        stack,
        trend_config=TrendConfig(min_samples=6, apply_fdr_for_pixels=True),
        spatial_config=SpatialConfig(chunk_rows=2, min_pixel_coverage=0.5),
    )
    assert res.slopes[0, 0] == pytest.approx(0.02, abs=1e-3)
    assert res.slopes[2, 0] == pytest.approx(0.0, abs=1e-6)
    assert np.isnan(res.slopes[3, 3])
    assert res.fdr_significant_fraction == pytest.approx(8.0 / 15.0)
    assert res.positive_fraction == pytest.approx(8.0 / 15.0)


def test_morans_i_and_getis_ord_hotspots_detect_clustered_high_vs_low_regions() -> None:
    # 6x6 surface with strongly clustered high values on top-left and low on bottom-right
    surface = np.full((6, 6), 0.5, dtype=np.float64)
    surface[:3, :3] = 0.9
    surface[3:, 3:] = 0.1

    ac = compute_morans_i_and_hotspots(surface, alpha=0.05, permutations=99, seed=123)
    assert ac.morans_i is not None and ac.morans_i > 0.4
    assert ac.morans_p_value is not None and ac.morans_p_value < 0.05
    assert ac.hotspot_significant_fraction > 0.0
    assert ac.coldspot_significant_fraction > 0.0
