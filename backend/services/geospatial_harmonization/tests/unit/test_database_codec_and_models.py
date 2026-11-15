"""Tests for GHS ORM table creation, JSON codecs, and async engine health."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    ProvenanceRecord,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import HarmonizationPlan
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    check_database_health,
    decode_dataset,
    decode_plan,
    encode_dataset,
    encode_plan,
    ensure_utc,
)


async def test_codec_round_trip_and_database_ddl_health(tmp_path: Path) -> None:
    bounds = SpatialBounds(0.0, 0.0, 2.0, 2.0)
    grid = GridSpec("EPSG:4326", 1.0, 1.0, "degree", bounds).resolved()
    temporal = TemporalSpec(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
        cadence="daily",
        semantics="interval",
    )
    ds = SpatialDataset(
        dataset_id=uuid4(),
        source_id="src-1",
        provider="modis",
        product="MOD13Q1.061",
        variables={
            "ndvi": VariableSpec("ndvi", "1", "float32", ("y", "x"), "continuous_intensive")
        },
        units={"ndvi": "1"},
        spatial_metadata=SpatialMetadata("raster", "EPSG:4326", bounds, grid),
        temporal_metadata=temporal,
        quality_metadata=QualityMetadata("strict", 0.9, 1, ("qa_mask",), ("pixel_reliability",)),
        assets=(AssetReference("raw/a.hdf", "file:///tmp/a.hdf", "hdf4", "application/x-hdf"),),
        provenance=ProvenanceRecord(
            "modis", "MOD13Q1.061", "061", datetime(2026, 7, 2, tzinfo=UTC), "0.1.0"
        ),
        extensions={"nested": {"flag": True}},
    )
    restored_ds = decode_dataset(encode_dataset(ds))
    assert restored_ds == ds

    plan = HarmonizationPlan(
        plan_id=uuid4(),
        provider="generic",
        product="custom",
        request_payload={
            "url": "https://example.org/a.tif",
            "ts": datetime(2026, 7, 1, tzinfo=UTC),
        },
        target_grid=grid,
        target_temporal=temporal,
        variables=("ndvi",),
    )
    restored_plan = decode_plan(encode_plan(plan))
    assert restored_plan.plan_id == plan.plan_id
    assert restored_plan.target_grid == plan.target_grid
    assert restored_plan.request_payload["ts"] == "2026-07-01T00:00:00Z"
    assert ensure_utc(datetime(2026, 7, 1, 0, 0)).tzinfo == UTC

    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ghs.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        assert await check_database_health(engine) is True
        assert {"ghs_datasets", "ghs_assets", "ghs_harmonization_jobs"} <= set(
            GhsBase.metadata.tables
        )
    finally:
        await engine.dispose()


def test_codec_replaces_non_finite_floats_with_null() -> None:
    """PostgreSQL JSON rejects NaN/Infinity; they must persist as explicit nulls."""
    import json

    from geospatial_harmonization.infrastructure.database.codec import _finite_json

    encoded = _finite_json(
        {"a": float("nan"), "b": [float("inf"), 1.0], "c": {"d": float("-inf")}}
    )
    assert encoded == {"a": None, "b": [None, 1.0], "c": {"d": None}}
    json.dumps(encoded, allow_nan=False)
