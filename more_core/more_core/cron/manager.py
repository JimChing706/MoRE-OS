"""Task Manager - combines scheduler and trigger engine."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from .scheduler import CronScheduler, JobResult
from .trigger import TriggerEngine, TriggerEvent, TriggerEventType, EventPattern

_log = logging.getLogger(__name__)

# ── Step-4 P0: global kill-switch registry ────────────────────────────
# Two levels of kill switch:
#   1. ``GLOBAL_KILLSWITCH.set(True)`` — *all* cron + trigger tasks stop
#      firing.  The scheduler itself keeps running so it can be revived;
#      wrappers simply return without invoking handlers.
#   2. ``TaskManager.kill_task(task_id)`` / ``rollback_task(task_id)`` —
#      per-job freeze + rollback hook.
_GLOBAL_LOCK = threading.Lock()
_GLOBAL_KILLSWITCH_ON: bool = False


def set_global_killswitch(on: bool) -> None:
    """Flip the global kill-switch.  Threadsafe; idempotent."""
    global _GLOBAL_KILLSWITCH_ON
    with _GLOBAL_LOCK:
        _GLOBAL_KILLSWITCH_ON = bool(on)


def get_global_killswitch() -> bool:
    with _GLOBAL_LOCK:
        return _GLOBAL_KILLSWITCH_ON


@dataclass
class RollbackRecord:
    """A single rollback entry — replayed in LIFO order by rollback_task()."""

    name: str
    rollback_fn: Callable[[], Awaitable[Any]] | Callable[[], Any]
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


@dataclass
class TaskDefinition:
    """Combined task definition."""

    task_id: str
    name: str
    task_type: str
    handler: Callable[..., Awaitable[Any]]
    schedule: str | None = None
    trigger_pattern: EventPattern | None = None
    args: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


class TaskManager:
    """Unified task management - combines cron and triggers."""

    def __init__(self) -> None:
        self._scheduler = CronScheduler()
        self._trigger_engine = TriggerEngine()
        self._tasks: dict[str, TaskDefinition] = {}
        self._running = False
        self._delivery_callbacks: list[Callable[[str, Any], Awaitable[None]]] = []
        # ── Step-4 P0: per-task kill state + rollback stack ────────
        self._killed: set[str] = set()
        self._rollbacks: dict[str, list[RollbackRecord]] = {}
        self._rollback_lock = threading.Lock()

    @property
    def scheduler(self) -> CronScheduler:
        """Get cron scheduler."""
        return self._scheduler

    @property
    def trigger_engine(self) -> TriggerEngine:
        """Get trigger engine."""
        return self._trigger_engine

    async def start(self) -> None:
        """Start the task manager."""
        self._running = True
        await self._scheduler.start()
        await self._trigger_engine.start()
        _log.info("Task manager started")

    async def stop(self) -> None:
        """Stop the task manager."""
        self._running = False
        await self._scheduler.stop()
        await self._trigger_engine.stop()
        _log.info("Task manager stopped")

    def add_cron_task(
        self,
        task_id: str,
        name: str,
        schedule: str,
        handler: Callable[..., Awaitable[Any]],
        args: dict[str, Any] | None = None,
        enabled: bool = True,
        description: str = "",
        **job_kwargs: Any,
    ) -> TaskDefinition:
        """Add a cron-based task."""
        task = TaskDefinition(
            task_id=task_id,
            name=name,
            task_type="cron",
            schedule=schedule,
            handler=handler,
            args=args or {},
            enabled=enabled,
            description=description,
        )

        self._scheduler.add_job(
            job_id=task_id,
            name=name,
            schedule=schedule,
            handler=self._create_wrapper(task),
            args=task.args,
            description=description,
            **job_kwargs,
        )

        self._tasks[task_id] = task
        _log.info(f"Added cron task: {task_id}")
        return task

    def add_trigger_task(
        self,
        task_id: str,
        name: str,
        pattern: EventPattern,
        handler: Callable[..., Awaitable[Any]],
        args: dict[str, Any] | None = None,
        enabled: bool = True,
        description: str = "",
        **trigger_kwargs: Any,
    ) -> TaskDefinition:
        """Add a trigger-based task."""
        task = TaskDefinition(
            task_id=task_id,
            name=name,
            task_type="trigger",
            trigger_pattern=pattern,
            handler=handler,
            args=args or {},
            enabled=enabled,
            description=description,
        )

        self._trigger_engine.add_trigger(
            trigger_id=task_id,
            name=name,
            pattern=pattern,
            handler=self._create_trigger_wrapper(task),
            description=description,
            **trigger_kwargs,
        )

        self._tasks[task_id] = task
        _log.info(f"Added trigger task: {task_id}")
        return task

    def remove_task(self, task_id: str) -> bool:
        """Remove a task."""
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]

        if task.task_type == "cron":
            self._scheduler.remove_job(task_id)
        elif task.task_type == "trigger":
            self._trigger_engine.remove_trigger(task_id)

        del self._tasks[task_id]
        _log.info(f"Removed task: {task_id}")
        return True

    def get_task(self, task_id: str) -> TaskDefinition | None:
        """Get a task."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[TaskDefinition]:
        """List all tasks."""
        return list(self._tasks.values())

    def enable_task(self, task_id: str) -> bool:
        """Enable a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.task_type == "cron":
            return self._scheduler.enable_job(task_id)
        elif task.task_type == "trigger":
            return self._trigger_engine.enable_trigger(task_id)
        return False

    def disable_task(self, task_id: str) -> bool:
        """Disable a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.task_type == "cron":
            return self._scheduler.disable_job(task_id)
        elif task.task_type == "trigger":
            return self._trigger_engine.disable_trigger(task_id)
        return False

    async def run_task(self, task_id: str) -> JobResult | None:
        """Manually run a task.

        Returns ``None`` when the global kill-switch or per-task kill is
        active (the job is not even scheduled into the handler).
        """
        if get_global_killswitch():
            _log.warning("run_task(%s) blocked by global kill-switch", task_id)
            return None
        task = self._tasks.get(task_id)
        if not task:
            return None
        if task_id in self._killed:
            _log.warning("run_task(%s) blocked by per-task kill", task_id)
            return None

        if task.task_type == "cron":
            return await self._scheduler.run_job(task_id)

        return None

    # ── Step-4 P0: kill / rollback APIs ─────────────────────────────

    def kill_task(self, task_id: str) -> bool:
        """Kill (freeze) a single task by id.  Fires disable + blacklist.

        Already-running executions of this task are not forcibly halted;
        future invocations return immediately from the wrapper.  Returns
        True when the task existed and is now disabled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        self._killed.add(task_id)
        self.disable_task(task_id)
        _log.warning("Task %s killed", task_id)
        return True

    def revive_task(self, task_id: str) -> bool:
        """Reverse :meth:`kill_task`: reinstate and enable.  Returns True when revived."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        self._killed.discard(task_id)
        self.enable_task(task_id)
        return True

    def add_rollback(
        self,
        task_id: str,
        *,
        name: str,
        rollback_fn: Callable[[], Awaitable[Any]] | Callable[[], Any],
    ) -> None:
        """Push a rollback function onto the LIFO stack for ``task_id``.

        Rollback functions are idempotently registered; they run only when
        :meth:`rollback_task` is called, most-recent-first order.
        """
        with self._rollback_lock:
            self._rollbacks.setdefault(task_id, []).append(
                RollbackRecord(name=name, rollback_fn=rollback_fn)
            )

    async def rollback_task(self, task_id: str) -> list[tuple[str, bool, str]]:
        """Execute all registered rollbacks for ``task_id`` in LIFO order.

        Returns a list of ``(rollback_name, succeeded, error)`` tuples so
        callers can build a remediation UI.  The call **never raises** —
        individual rollback exceptions are captured as ``(name, False,
        repr(exc))`` entries.
        """
        with self._rollback_lock:
            stack = list(reversed(self._rollbacks.pop(task_id, [])))
        result: list[tuple[str, bool, str]] = []
        import asyncio

        for rec in stack:
            try:
                maybe_coro = rec.rollback_fn()
                if asyncio.iscoroutine(maybe_coro):
                    await maybe_coro
                result.append((rec.name, True, ""))
            except Exception as exc:  # pragma: no cover - defensive
                result.append((rec.name, False, repr(exc)))
        return result

    def get_killswitch_state(self) -> dict[str, Any]:
        """Structured snapshot for /monitor/health endpoints."""
        return {
            "global_killed": get_global_killswitch(),
            "task_count_killed": len(self._killed),
            "killed_task_ids": sorted(self._killed),
            "tasks_with_rollbacks": sorted(self._rollbacks.keys()),
        }

    # ── end Step-4 P0 ────────────────────────────────────────────────

    def set_delivery_callback(self, callback: Callable[[str, Any], Awaitable[None]]) -> None:
        """Set callback for task result delivery."""
        self._delivery_callbacks.append(callback)

    async def _deliver_result(self, task_id: str, result: Any) -> None:
        """Deliver task result via callbacks."""
        for callback in self._delivery_callbacks:
            try:
                await callback(task_id, result)
            except Exception as e:
                _log.error(f"Delivery callback error: {e}")

    def _create_wrapper(self, task: TaskDefinition) -> Callable[[], Awaitable[Any]]:
        """Create wrapper for cron task handler."""

        async def wrapper() -> Any:
            # Step-4 P0 kill-switch short-circuits — both global and per-task.
            if get_global_killswitch():
                _log.warning("cron task %s blocked by global kill-switch", task.task_id)
                return None
            if task.task_id in self._killed:
                _log.warning("cron task %s blocked by per-task kill", task.task_id)
                return None
            try:
                result = await task.handler(**task.args)
                await self._deliver_result(task.task_id, result)
                return result
            except Exception as e:
                _log.error(f"Task {task.task_id} failed: {e}")
                raise

        return wrapper

    def _create_trigger_wrapper(
        self, task: TaskDefinition
    ) -> Callable[[TriggerEvent], Awaitable[Any]]:
        """Create wrapper for trigger task handler."""

        async def wrapper(event: TriggerEvent) -> Any:
            if get_global_killswitch():
                _log.warning("trigger %s blocked by global kill-switch", task.task_id)
                return None
            if task.task_id in self._killed:
                _log.warning("trigger %s blocked by per-task kill", task.task_id)
                return None
            try:
                result = await task.handler(event=event, **task.args)
                await self._deliver_result(task.task_id, result)
                return result
            except Exception as e:
                _log.error(f"Trigger task {task.task_id} failed: {e}")
                raise

        return wrapper

    def get_status(self) -> dict[str, Any]:
        """Get overall status."""
        cron_jobs = self._scheduler.list_jobs()
        triggers = self._trigger_engine.list_triggers()

        return {
            "running": self._running,
            "tasks": {
                "total": len(self._tasks),
                "cron": len([t for t in self._tasks.values() if t.task_type == "cron"]),
                "trigger": len([t for t in self._tasks.values() if t.task_type == "trigger"]),
            },
            "scheduler": {
                "jobs": len(cron_jobs),
                "enabled": len([j for j in cron_jobs if j.enabled]),
            },
            "triggers": {
                "total": len(triggers),
                "enabled": len([t for t in triggers if t.enabled]),
            },
        }

    async def emit_trigger_event(
        self,
        event_type: TriggerEventType,
        source: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit a trigger event."""
        await self._trigger_engine.emit_simple(event_type, source, data)
