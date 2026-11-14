"""Durable polling worker claiming PostgreSQL SKIP LOCKED harmonization jobs."""

import asyncio
import logging
import os
import socket
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime

from geospatial_harmonization.application.harmonize import HarmonizationService
from geospatial_harmonization.domain.models.harmonization import HarmonizationJob
from geospatial_harmonization.domain.ports import JobRepository
from geospatial_harmonization.storage.lifecycle import StorageLifecycleManager
from geospatial_harmonization.storage.quota import StorageQuotaManager

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
        max_concurrency: int = 1,
        maintenance_interval_seconds: float = 60.0,
        quota: StorageQuotaManager | None = None,
        lifecycle: StorageLifecycleManager | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._jobs = jobs
        self._worker_id = worker_id or _default_worker_id()
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval_seconds
        self._max_concurrency = max(1, max_concurrency)
        self._maintenance_interval = max(1.0, maintenance_interval_seconds)
        self._quota = quota
        self._lifecycle = lifecycle
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_maintenance_at: datetime | None = None

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    async def run_maintenance(self) -> None:
        """Reconcile expired reservations and execute storage lifecycle maintenance."""
        now = self._clock()
        if self._quota is not None:
            expired = await self._quota.reconcile_expired_reservations(now=now)
            if expired:
                logger.info("Reconciled %d expired storage reservations", len(expired))
        if self._lifecycle is not None:
            await self._lifecycle.run_maintenance_cycle(dry_run=False, now=now)
        self._last_maintenance_at = now

    async def _maybe_run_maintenance(self) -> None:
        if self._quota is None and self._lifecycle is None:
            return
        now = self._clock()
        if (
            self._last_maintenance_at is not None
            and (now - self._last_maintenance_at).total_seconds() < self._maintenance_interval
        ):
            return
        try:
            await self.run_maintenance()
        except Exception:
            logger.exception("Worker storage maintenance cycle failed")

    async def _execute_claimed_job(self, job: HarmonizationJob) -> None:
        try:
            result = await self._service.execute_plan(job.plan, job_id=job.job_id)
        except Exception as exc:
            logger.exception("Harmonization job %s failed", job.job_id)
            await self._jobs.mark_failed(job.job_id, f"{type(exc).__name__}: {exc}", self._clock())
            if self._lifecycle is not None:
                try:
                    await self._lifecycle.on_job_completed(
                        str(job.job_id), success=False, now=self._clock()
                    )
                except Exception:
                    logger.warning("Cleanup failed after error on job %s", job.job_id)
            return
        await self._jobs.mark_succeeded(job.job_id, result.dataset.dataset_id, self._clock())

    async def run_once(self) -> bool:
        """Claim and process at most one pending job; return True if a job was executed."""
        job = await self._jobs.claim_next_pending(
            self._worker_id, self._lease_seconds, self._clock()
        )
        if job is None:
            return False
        await self._execute_claimed_job(job)
        return True

    async def drain(self, max_jobs: int = 100) -> int:
        """Process queued jobs up to max_concurrency until empty or max_jobs limit reached."""
        await self._maybe_run_maintenance()
        if self._max_concurrency <= 1:
            processed = 0
            while processed < max_jobs and await self.run_once():
                processed += 1
            return processed

        semaphore = asyncio.Semaphore(self._max_concurrency)
        active: set[asyncio.Task[None]] = set()
        claimed = 0

        async def _run_bounded(job: HarmonizationJob) -> None:
            async with semaphore:
                await self._execute_claimed_job(job)

        while True:
            while claimed < max_jobs and len(active) < self._max_concurrency:
                job = await self._jobs.claim_next_pending(
                    self._worker_id, self._lease_seconds, self._clock()
                )
                if job is None:
                    break
                claimed += 1
                task = asyncio.create_task(_run_bounded(job))
                active.add(task)
                task.add_done_callback(active.discard)
            if not active:
                break
            done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                await t
            if claimed >= max_jobs and not active:
                break
        return claimed

    async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
        """Continuously poll with bounded concurrency and periodic storage maintenance."""
        semaphore = asyncio.Semaphore(self._max_concurrency)
        active: set[asyncio.Task[None]] = set()

        async def _run_bounded(job: HarmonizationJob) -> None:
            async with semaphore:
                await self._execute_claimed_job(job)

        try:
            while not stop_event.is_set():
                await self._maybe_run_maintenance()
                while len(active) < self._max_concurrency and not stop_event.is_set():
                    job = await self._jobs.claim_next_pending(
                        self._worker_id, self._lease_seconds, self._clock()
                    )
                    if job is None:
                        break
                    task = asyncio.create_task(_run_bounded(job))
                    active.add(task)
                    task.add_done_callback(active.discard)

                if active:
                    stop_waiter = asyncio.create_task(stop_event.wait())
                    try:
                        wait_set: set[asyncio.Task[object]] = {*active, stop_waiter}
                        done, _ = await asyncio.wait(
                            wait_set,
                            timeout=self._poll_interval,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for t in done:
                            if t is not stop_waiter:
                                await t
                    finally:
                        if not stop_waiter.done():
                            stop_waiter.cancel()
                            with suppress(asyncio.CancelledError):
                                await stop_waiter
                else:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)
        finally:
            if active:
                await asyncio.gather(*active, return_exceptions=True)
