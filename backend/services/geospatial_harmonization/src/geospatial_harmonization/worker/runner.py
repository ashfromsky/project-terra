"""Durable polling worker claiming PostgreSQL SKIP LOCKED harmonization jobs."""

import asyncio
import logging
import os
import socket
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime

from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.domain.ports import JobRepository

logger = logging.getLogger(__name__)


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class WorkerRunner:
    """Claims queued HarmonizationJobs, executes HarmonizationService, updates status."""

    def __init__(
        self,
        *,
        service: HarmonizationService,
        jobs: JobRepository,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        poll_interval_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._jobs = jobs
        self._worker_id = worker_id or _default_worker_id()
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self) -> bool:
        """Claim and process at most one pending job; return True if a job was executed."""
        job = await self._jobs.claim_next_pending(
            self._worker_id, self._lease_seconds, self._clock()
        )
        if job is None:
            return False
        try:
            result = await self._service.execute_plan(job.plan, job_id=job.job_id)
        except Exception as exc:
            logger.exception("Harmonization job %s failed", job.job_id)
            await self._jobs.mark_failed(job.job_id, f"{type(exc).__name__}: {exc}", self._clock())
            return True
        await self._jobs.mark_succeeded(job.job_id, result.dataset.dataset_id, self._clock())
        return True

    async def drain(self, max_jobs: int = 100) -> int:
        """Process queued jobs until empty or max_jobs limit reached."""
        processed = 0
        while processed < max_jobs and await self.run_once():
            processed += 1
        return processed

    async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
        """Continuously poll for jobs until stop_event is signaled."""
        while not stop_event.is_set():
            did_work = await self.run_once()
            if not did_work:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)
