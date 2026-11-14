"""Unit/repository tests against async SQLite for DatasetRepository and JobRepository."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from geospatial_harmonization.domain.models.dataset import (
    AssetReference,
    ProvenanceRecord,
    QualityMetadata,
    SpatialDataset,
    SpatialMetadata,
    VariableSpec,
)
from geospatial_harmonization.domain.models.grid import GridSpec, SpatialBounds
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob, HarmonizationPlan
from geospatial_harmonization.domain.models.temporal import TemporalSpec
from geospatial_harmonization.domain.ports import DatasetRepository, JobRepository
from geospatial_harmonization.infrastructure.database import (
    GhsBase,
    build_async_engine,
    build_session_factory,
)
from geospatial_harmonization.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyJobRepository,
)


def _sample_dataset(provider: str, retrieved_at: datetime) -> SpatialDataset:
    bounds = SpatialBounds(0.0, 0.0, 2.0, 2.0)
    grid = GridSpec("EPSG:4326", 1.0, 1.0, "degree", bounds).resolved()
    temporal = TemporalSpec(
        start=datetime(2026, 7, 1, tzinfo=UTC),
        end=datetime(2026, 7, 2, tzinfo=UTC),
        cadence="daily",
        semantics="interval",
    )
    return SpatialDataset(
        dataset_id=uuid4(),
        source_id=f"src-{provider}",
        provider=provider,
        product="PROD1",
        variables={"v": VariableSpec("v", "1", "float32", ("y", "x"), "continuous_intensive")},
        units={"v": "1"},
        spatial_metadata=SpatialMetadata("raster", "EPSG:4326", bounds, grid),
        temporal_metadata=temporal,
        quality_metadata=QualityMetadata("strict", 1.0),
        assets=(AssetReference("derived/v.tif", "file:///v.tif", "geotiff", "image/tiff"),),
        provenance=ProvenanceRecord(provider, "PROD1", "1", retrieved_at, "0.1.0"),
    )


def _sample_job(created_at: datetime, *, max_attempts: int = 2) -> HarmonizationJob:
    plan = HarmonizationPlan(
        plan_id=uuid4(),
        provider="generic",
        product="custom",
        request_payload={"url": "https://example.org/a.tif"},
    )
    return HarmonizationJob(
        job_id=uuid4(),
        plan=plan,
        status="pending",
        created_at=created_at,
        updated_at=created_at,
        max_attempts=max_attempts,
    )


async def test_dataset_repository_save_upsert_and_filter(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ds.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        repo: DatasetRepository = SqlAlchemyDatasetRepository(build_session_factory(engine))
        t0 = datetime(2026, 7, 1, tzinfo=UTC)
        ds1 = _sample_dataset("modis", t0)
        ds2 = _sample_dataset("smap", t0 + timedelta(minutes=5))
        await repo.save(ds1)
        await repo.save(ds2)
        await repo.save(ds1)

        assert await repo.get_by_id(ds1.dataset_id) == ds1
        assert await repo.get_by_id(uuid4()) is None
        recent = await repo.list_recent(limit=10)
        assert [d.dataset_id for d in recent] == [ds2.dataset_id, ds1.dataset_id]
        modis_only = await repo.list_recent(limit=10, provider="modis")
        assert [d.dataset_id for d in modis_only] == [ds1.dataset_id]
    finally:
        await engine.dispose()


async def test_job_repository_claim_concurrency_lease_reclaim_and_retries(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(GhsBase.metadata.create_all)
        repo: JobRepository = SqlAlchemyJobRepository(build_session_factory(engine))
        t0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        job = _sample_job(t0, max_attempts=2)
        await repo.create(job)

        c1, c2 = await asyncio.gather(
            repo.claim_next_pending("w1", 60, t0 + timedelta(seconds=1)),
            repo.claim_next_pending("w2", 60, t0 + timedelta(seconds=1)),
        )
        claimed = [c for c in (c1, c2) if c is not None]
        assert len(claimed) == 1
        assert claimed[0].attempt == 1
        assert claimed[0].status == "running"

        assert await repo.claim_next_pending("w3", 60, t0 + timedelta(seconds=10)) is None
        reclaimed = await repo.claim_next_pending("w3", 60, t0 + timedelta(seconds=120))
        assert reclaimed is not None and reclaimed.locked_by == "w3" and reclaimed.attempt == 2

        await repo.mark_failed(job.job_id, "terminal", t0 + timedelta(seconds=130))
        failed = await repo.get_by_id(job.job_id)
        assert failed is not None
        assert failed.status == "failed" and failed.error_message == "terminal"

        job2 = _sample_job(t0 + timedelta(minutes=1), max_attempts=2)
        await repo.create(job2)
        first = await repo.claim_next_pending("w1", 60, t0 + timedelta(minutes=2))
        assert first is not None and first.attempt == 1
        await repo.mark_failed(job2.job_id, "transient", t0 + timedelta(minutes=3))
        retried = await repo.get_by_id(job2.job_id)
        assert retried is not None and retried.status == "pending"
        second = await repo.claim_next_pending("w2", 60, t0 + timedelta(minutes=4))
        assert second is not None and second.attempt == 2
        ds_id = uuid4()
        await repo.mark_succeeded(job2.job_id, ds_id, t0 + timedelta(minutes=5))
        done = await repo.get_by_id(job2.job_id)
        assert done is not None and done.status == "succeeded" and done.dataset_id == ds_id
        with pytest.raises(LookupError):
            await repo.mark_succeeded(uuid4(), ds_id, t0)
    finally:
        await engine.dispose()
