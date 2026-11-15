"""Performance regression checks ensuring chunked grid trend stays fast & bounded."""

import time
from datetime import UTC, datetime

import numpy as np

from terra_scientific.domain.enums import DataSourceId, VariableSemanticKind
from terra_scientific.domain.models.dataset import (
    ScientificGridStack,
    SpatialSupport,
    VariableMetadata,
)
from terra_scientific.domain.models.request import SpatialConfig, TrendConfig
from terra_scientific.spatial.pixel_trends import compute_chunked_pixel_trends


def test_chunked_pixel_trend_handles_64x64_grid_over_30_steps_within_budget() -> None:
    rng = np.random.default_rng(7)
    ts = [datetime(1995 + i, 1, 1, tzinfo=UTC) for i in range(30)]
    data = rng.normal(loc=0.5, scale=0.1, size=(30, 64, 64))
    meta = VariableMetadata(
        name="NDVI",
        canonical_name="ndvi",
        units="dimensionless",
        semantic_kind=VariableSemanticKind.CONTINUOUS_INTENSIVE,
    )
    stack = ScientificGridStack(
        dataset_id="perf-1",
        source_id=DataSourceId.MODIS_MOD13Q1,
        product="MOD13Q1.061",
        product_version="061",
        variable=meta,
        spatial_support=SpatialSupport(crs="EPSG:4326", nominal_resolution_m=250.0),
        timestamps=ts,
        data=data,
    )
    start = time.perf_counter()
    res = compute_chunked_pixel_trends(
        stack,
        trend_config=TrendConfig(min_samples=10),
        spatial_config=SpatialConfig(chunk_rows=16),
    )
    elapsed = time.perf_counter() - start
    assert res.slopes.shape == (64, 64)
    # Vectorized chunked execution across 4,096 pixels x 30 steps should finish well under 3 seconds
    assert elapsed < 3.0
