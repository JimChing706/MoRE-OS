from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from more_core.cron.scheduler import CronParser, CronScheduler


def _ts(dt: datetime) -> float:
    return dt.replace(tzinfo=timezone.utc).timestamp()


def test_parse_weekday_star_is_supported() -> None:
    spec = CronParser.parse("* * * * *")
    assert spec.weekdays == frozenset(range(0, 7))
    assert spec.days == frozenset(range(1, 32))


def test_get_next_run_every_minute() -> None:
    before = datetime(2026, 8, 2, 10, 0, 0)
    nxt = CronParser.get_next_run("* * * * *", after=_ts(before))
    assert nxt is not None
    assert _ts(before) < nxt <= _ts(before) + 60


def test_get_next_run_step_schedule() -> None:
    nxt = CronParser.get_next_run("*/5 * * * *", after=_ts(datetime(2026, 8, 2, 10, 0, 0)))
    assert nxt is not None
    assert nxt == _ts(datetime(2026, 8, 2, 10, 5, 0))


def test_get_next_run_weekday_constraint_not_daily() -> None:
    nxt = CronParser.get_next_run("0 0 * * 0", after=_ts(datetime(2026, 8, 2, 0, 0, 0)))
    assert nxt == _ts(datetime(2026, 8, 9, 0, 0, 0))


def test_get_next_run_weekday_range_constraint() -> None:
    after = _ts(datetime(2026, 8, 7, 8, 0, 0))  # Friday
    nxt = CronParser.get_next_run("0 9 * * 1-5", after=after)
    assert nxt == _ts(datetime(2026, 8, 7, 9, 0, 0))


def test_get_next_run_day_of_month_constraint_not_daily() -> None:
    nxt = CronParser.get_next_run("0 0 1 * *", after=_ts(datetime(2026, 8, 2, 0, 0, 0)))
    assert nxt == _ts(datetime(2026, 9, 1, 0, 0, 0))


def test_scheduler_add_job_every_minute_gets_next_run() -> None:
    scheduler = CronScheduler()
    job = scheduler.add_job("j1", "tick", "* * * * *", handler=asyncio.sleep)
    assert job.next_run is not None


@pytest.mark.asyncio
async def test_scheduler_executes_job_on_trigger() -> None:
    scheduler = CronScheduler()
    ran: list[str] = []

    async def handler(tag: str) -> None:
        ran.append(tag)

    scheduler.add_job("j2", "job", "* * * * *", handler=handler, args={"tag": "x"})
    job = scheduler.get_job("j2")
    assert job is not None
    job.next_run = 0  # force trigger
    await scheduler.run_job("j2")
    assert ran == ["x"]
