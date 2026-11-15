"""Integration tests for AssessmentWorkerRunner queueing, claiming, execution, and failures."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from terra.config import Settings
from terra.infrastructure.database import DatabaseManager
from terra.modules.assessments.application.services import AssessmentApplicationService
from terra.modules.assessments.domain.entities import ScientificAssessment
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.assessments.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyAssessmentRepository,
)
from terra.modules.auth.infrastructure.models import UserModel
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository

from terra_worker.runner import AssessmentWorkerRunner


def _sample_mod13_payload() -> dict[str, object]:
    timestamps = [
        datetime(year, month, 1, tzinfo=UTC).isoformat()
        for year in range(2018, 2025)
        for month in range(1, 13)
    ]
    values = [round(0.55 + 0.01 * (idx // 12), 4) for idx in range(len(timestamps))]
    qa = [0 for _ in timestamps]
    meta = {
        "name": "NDVI",
        "canonical_name": "ndvi",
        "units": "dimensionless",
        "semantic_kind": "continuous_intensive",
        "scale_factor": 0.0001,
        "is_scaled": True,
        "fill_values": [-3000.0],
        "valid_range": [-0.2, 1.0],
    }
    return {
        "dataset_id": "mod13-worker-sample",
        "source_id": "modis_mod13q1",
        "product": "MOD13Q1.061",
        "product_version": "061",
        "provider": "nasa_earthdata",
        "spatial_support": {"crs": "EPSG:4326", "nominal_resolution_m": 250.0},
        "temporal_metadata": {
            "cadence": "monthly",
            "semantics": "composite",
            "composite_days": 16,
            "start": timestamps[0],
            "end": timestamps[-1],
        },
        "variables": {"NDVI": meta},
        "series": {
            "NDVI": {
                "timestamps": timestamps,
                "values": values,
                "qa_layers": {"pixel_reliability": qa},
                "metadata": meta,
            }
        },
    }


def _request_config(req_id: str) -> dict[str, object]:
    return {
        "request_id": req_id,
        "analysis_start": "2021-01-01T00:00:00Z",
        "analysis_end": "2024-12-31T00:00:00Z",
        "target_cadence": "monthly",
        "baseline": {
            "baseline_type": "fixed_reference",
            "start": "2018-01-01T00:00:00Z",
            "end": "2020-12-31T00:00:00Z",
            "min_years_required": 3,
            "min_samples_per_bin": 3,
        },
    }


@pytest.mark.asyncio
async def test_worker_drains_queued_assessments_and_isolates_failures(tmp_path: Path) -> None:
    def _mock_ghs(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": f"Missing {request.url.path}"})

    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        ghs_base_url="http://ghs.test",
        scientific_artifact_dir=str(tmp_path),
    )
    db = DatabaseManager(settings)
    await db.create_schema()

    try:
        owner_id = uuid4()
        async with db.session() as session:
            session.add(
                UserModel(
                    id=owner_id,
                    github_id=9001,
                    github_login="worker_tester",
                )
            )
            await session.commit()

            service = AssessmentApplicationService(
                repo=SqlAlchemyAssessmentRepository(session),
                region_repo=SqlAlchemyRegionRepository(session),
                ghs_client=HttpxGhsDatasetClient(
                    settings, transport=httpx.MockTransport(_mock_ghs)
                ),
                artifact_root=str(tmp_path),
            )
            bad_queued = await service.create_assessment(
                owner_id=owner_id,
                title="Missing GHS Job",
                region_id=None,
                execute_now=False,
                request_config=_request_config("worker-req-fail"),
                ghs_dataset_ids=["nonexistent-ghs-id"],
                inline_datasets=[],
            )
            good_queued = await service.create_assessment(
                owner_id=owner_id,
                title="Inline Valid Job",
                region_id=None,
                execute_now=False,
                request_config=_request_config("worker-req-ok"),
                ghs_dataset_ids=[],
                inline_datasets=[_sample_mod13_payload()],
            )

        runner = AssessmentWorkerRunner(
            settings=settings,
            db=db,
            ghs_client_factory=lambda s: HttpxGhsDatasetClient(
                s, transport=httpx.MockTransport(_mock_ghs)
            ),
            poll_interval_seconds=0.05,
        )

        # Empty check after draining
        outcomes: list[ScientificAssessment] = await runner.drain_queue()
        assert len(outcomes) == 2
        by_id = {item.id: item for item in outcomes}

        assert by_id[bad_queued.id].status == "failed"
        assert by_id[bad_queued.id].error_message is not None
        assert by_id[good_queued.id].status == "completed"
        assert by_id[good_queued.id].result_payload is not None
        assert by_id[good_queued.id].artifact_paths["assessment_result_json"]
        assert Path(by_id[good_queued.id].artifact_paths["assessment_result_json"]).exists()

        # Queue is now empty
        assert await runner.run_once() is None
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_worker_run_forever_respects_stop_event() -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    runner = AssessmentWorkerRunner(settings=settings, poll_interval_seconds=0.02)
    stop_event = asyncio.Event()
    task = asyncio.create_task(runner.run_forever(stop_event=stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)
