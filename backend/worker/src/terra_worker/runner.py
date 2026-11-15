"""Async background runner claiming queued assessments from Core DB and running Scientific Core."""

import asyncio
import logging
from collections.abc import Callable

from terra.config import Settings, get_settings
from terra.infrastructure.database import DatabaseManager
from terra.modules.assessments.application.services import AssessmentApplicationService
from terra.modules.assessments.domain.entities import ScientificAssessment
from terra.modules.assessments.domain.ports import GhsDatasetClient
from terra.modules.assessments.infrastructure.ghs_client import HttpxGhsDatasetClient
from terra.modules.assessments.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyAssessmentRepository,
)
from terra.modules.regions.infrastructure.repositories.sqlalchemy import SqlAlchemyRegionRepository
from terra_scientific import ScientificAssessmentService

logger = logging.getLogger("terra.worker")


class AssessmentWorkerRunner:
    """Claims queued assessments atomically and runs them via ScientificAssessmentService."""

    def __init__(
        self,
        settings: Settings | None = None,
        db: DatabaseManager | None = None,
        ghs_client_factory: Callable[[Settings], GhsDatasetClient] | None = None,
        scientific_service: ScientificAssessmentService | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_db = db is None
        self._db = db or DatabaseManager(self._settings)
        self._ghs_client_factory = ghs_client_factory or (lambda s: HttpxGhsDatasetClient(s))
        self._scientific_service = scientific_service or ScientificAssessmentService()
        self._poll_interval = poll_interval_seconds

    async def initialize(self) -> None:
        """Ensure non-production schema exists when running standalone worker."""
        if (
            self._settings.database_auto_create_tables
            and self._settings.environment != "production"
        ):
            await self._db.create_schema()

    async def dispose(self) -> None:
        """Dispose worker-owned DatabaseManager resources cleanly."""
        if self._owns_db:
            await self._db.dispose()

    async def run_once(self) -> ScientificAssessment | None:
        """Claim one queued assessment, execute it, and return the final persisted record."""
        async with self._db.session() as session:
            repo = SqlAlchemyAssessmentRepository(session)
            claimed = await repo.claim_next_queued()
            if claimed is None:
                return None

            region_repo = SqlAlchemyRegionRepository(session)
            ghs_client = self._ghs_client_factory(self._settings)
            service = AssessmentApplicationService(
                repo=repo,
                region_repo=region_repo,
                ghs_client=ghs_client,
                artifact_root=self._settings.scientific_artifact_dir,
                scientific_service=self._scientific_service,
            )
            try:
                completed = await service.execute_claimed_assessment(claimed)
                logger.info(
                    "Assessment %s finished with status=%s",
                    completed.id,
                    completed.status,
                )
                return completed
            except Exception as exc:
                logger.exception(
                    "Assessment %s failed during worker execution: %s", claimed.id, exc
                )
                failed = await repo.get_by_id(claimed.id)
                return failed or claimed

    async def drain_queue(self, max_jobs: int | None = None) -> list[ScientificAssessment]:
        """Process currently queued assessments sequentially until empty or max_jobs reached."""
        processed: list[ScientificAssessment] = []
        while max_jobs is None or len(processed) < max_jobs:
            outcome = await self.run_once()
            if outcome is None:
                break
            processed.append(outcome)
        return processed

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """Continuously poll for queued assessments until stop_event is signaled."""
        halt = stop_event or asyncio.Event()
        await self.initialize()
        try:
            while not halt.is_set():
                outcome = await self.run_once()
                if outcome is not None:
                    continue
                try:
                    await asyncio.wait_for(halt.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    continue
        finally:
            await self.dispose()
