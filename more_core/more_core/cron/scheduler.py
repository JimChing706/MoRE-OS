"""Cron scheduler for scheduled tasks."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

_log = logging.getLogger(__name__)


class JobStatus(Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobResult:
    """Result of a job execution."""

    job_id: str
    status: JobStatus
    output: Any = None
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0


@dataclass
class CronJob:
    """Cron job definition."""

    job_id: str
    name: str
    schedule: str
    handler: Callable[..., Awaitable[Any]]
    args: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    max_retries: int = 0
    timeout_s: int = 300
    description: str = ""
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    last_run: float | None = None
    next_run: float | None = None
    run_count: int = 0


class CronParser:
    """Parse cron expressions."""

    CRON_PATTERN = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(.*))?$")

    SIMPLE_PATTERNS = {
        "every minute": "* * * * *",
        "every 5 minutes": "*/5 * * * *",
        "every 15 minutes": "*/15 * * * *",
        "every 30 minutes": "*/30 * * * *",
        "every hour": "0 * * * *",
        "every day": "0 0 * * *",
        "every week": "0 0 * * 0",
        "every month": "0 0 1 * *",
    }

    @classmethod
    def parse(cls, schedule: str) -> list[int]:
        """Parse cron schedule and return next run times (minute intervals)."""
        if schedule in cls.SIMPLE_PATTERNS:
            schedule = cls.SIMPLE_PATTERNS[schedule]

        match = cls.CRON_PATTERN.match(schedule)
        if not match:
            raise ValueError(f"Invalid cron expression: {schedule}")

        minute, hour, day, month, weekday = match.groups()[:5]

        return cls._parse_field(minute, 0, 59)

    @classmethod
    def _parse_field(cls, field: str, min_val: int, max_val: int) -> list[int]:
        """Parse a single cron field."""
        values: list[int] = []

        for part in field.split(","):
            if "/" in part:
                base, step_str = part.split("/")
                step = int(step_str)
                start: int = cls._parse_single(base, min_val, max_val) if base != "*" else min_val
                values.extend(range(start, max_val + 1, step))
            elif "-" in part:
                start_str, end_str = part.split("-")
                start = int(start_str)
                end = int(end_str)
                values.extend(range(start, end + 1))
            elif part == "*":
                values.extend(range(min_val, max_val + 1))
            else:
                values.append(int(part))

        return sorted(set(values))

    @classmethod
    def _parse_single(cls, value: str, min_val: int, max_val: int) -> int:
        """Parse a single value."""
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Invalid cron value: {value}")

    @classmethod
    def get_next_run(cls, schedule: str, after: float | None = None) -> float | None:
        """Calculate next run time after given timestamp.

        Handles cross-hour, cross-day, and cross-month boundaries by
        advancing in 1-hour increments up to 31 days (max cron window).
        """
        if after is None:
            after = datetime.now(timezone.utc).timestamp()

        try:
            minutes = cls.parse(schedule)
        except ValueError:
            return None

        now = datetime.fromtimestamp(after, timezone.utc)

        # Search forward in 1-hour increments (capped at 31 days)
        from datetime import timedelta

        for hour_offset in range(24 * 31):
            candidate_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(
                hours=hour_offset
            )
            for minute in minutes:
                next_time = candidate_hour.replace(minute=minute)
                if next_time.timestamp() > after:
                    return next_time.timestamp()

        return None


class CronScheduler:
    """Cron-based task scheduler."""

    def __init__(self) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._results: dict[str, JobResult] = {}

    def add_job(
        self,
        job_id: str,
        name: str,
        schedule: str,
        handler: Callable[..., Awaitable[Any]],
        args: dict[str, Any] | None = None,
        enabled: bool = True,
        max_retries: int = 0,
        timeout_s: int = 300,
        description: str = "",
    ) -> CronJob:
        """Add a cron job."""
        job = CronJob(
            job_id=job_id,
            name=name,
            schedule=schedule,
            handler=handler,
            args=args or {},
            enabled=enabled,
            max_retries=max_retries,
            timeout_s=timeout_s,
            description=description,
        )

        job.next_run = CronParser.get_next_run(schedule)
        self._jobs[job_id] = job

        _log.info(f"Added cron job: {job_id} ({schedule})")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            _log.info(f"Removed cron job: {job_id}")
            return True
        return False

    def get_job(self, job_id: str) -> CronJob | None:
        """Get a cron job."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[CronJob]:
        """List all cron jobs."""
        return list(self._jobs.values())

    def enable_job(self, job_id: str) -> bool:
        """Enable a cron job."""
        job = self._jobs.get(job_id)
        if job:
            job.enabled = True
            job.next_run = CronParser.get_next_run(job.schedule)
            return True
        return False

    def disable_job(self, job_id: str) -> bool:
        """Disable a cron job."""
        job = self._jobs.get(job_id)
        if job:
            job.enabled = False
            job.next_run = None
            return True
        return False

    async def start(self) -> None:
        """Start the scheduler."""
        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        _log.info("Cron scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        _log.info("Cron scheduler stopped")

    async def run_job(self, job_id: str) -> JobResult:
        """Manually trigger a job."""
        job = self._jobs.get(job_id)
        if not job:
            return JobResult(
                job_id=job_id,
                status=JobStatus.FAILED,
                error="Job not found",
            )

        return await self._execute_job(job)

    async def _run_scheduler(self) -> None:
        """Main scheduler loop."""
        while self._running:
            now = datetime.now(timezone.utc).timestamp()

            for job in self._jobs.values():
                if not job.enabled:
                    continue

                if job.next_run and job.next_run <= now:
                    asyncio.create_task(self._execute_job(job))

            await asyncio.sleep(10)

    async def _execute_job(self, job: CronJob) -> JobResult:
        """Execute a cron job."""
        start_time = datetime.now(timezone.utc).timestamp()

        result = JobResult(
            job_id=job.job_id,
            status=JobStatus.RUNNING,
            started_at=start_time,
        )

        self._results[job.job_id] = result
        _log.info(f"Executing job: {job.name}")

        for attempt in range(job.max_retries + 1):
            try:
                if job.timeout_s:
                    output = await asyncio.wait_for(
                        job.handler(**job.args),
                        timeout=job.timeout_s,
                    )
                else:
                    output = await job.handler(**job.args)

                result.status = JobStatus.COMPLETED
                result.output = output
                break

            except asyncio.TimeoutError:
                result.error = f"Timeout after {job.timeout_s}s"
                if attempt == job.max_retries:
                    result.status = JobStatus.FAILED

            except Exception as e:
                result.error = str(e)
                if attempt == job.max_retries:
                    result.status = JobStatus.FAILED

        finish_time = datetime.now(timezone.utc).timestamp()
        result.finished_at = finish_time
        result.duration_ms = (finish_time - start_time) * 1000

        job.last_run = finish_time
        job.run_count += 1
        job.next_run = CronParser.get_next_run(job.schedule, finish_time)

        _log.info(f"Job {job.name} completed: {result.status.value} ({result.duration_ms:.0f}ms)")

        return result

    def get_job_result(self, job_id: str) -> JobResult | None:
        """Get result of last job execution."""
        return self._results.get(job_id)

    def get_all_results(self) -> dict[str, JobResult]:
        """Get all job results."""
        return self._results.copy()
