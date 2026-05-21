"""Workflow Engine — DAG-based multi-step orchestration.

Supports:
- Sequential and parallel step execution
- Step types: hand, skill, task, webhook, condition
- Step dependencies (DAG)
- Real-time status streaming
- Timeout and retry per step
- Workflow-level variables and context passing
"""

from __future__ import annotations

import ast
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

_log = logging.getLogger(__name__)


class StepType(Enum):
    HAND = "hand"
    SKILL = "skill"
    TASK = "task"
    WEBHOOK = "webhook"
    CONDITION = "condition"
    DELAY = "delay"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class WorkflowStatus(Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    name: str
    type: StepType
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    timeout_s: int = 300
    retry_count: int = 0
    condition: str | None = None  # Python expression for conditional steps

    # Runtime state
    status: StepStatus = StepStatus.PENDING
    output: Any = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    attempts: int = 0

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return 0


@dataclass
class WorkflowDefinition:
    """Declarative workflow definition."""
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    steps: list[WorkflowStep] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    schedule: str | None = None  # Cron expression for auto-trigger
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def get_step(self, step_id: str) -> WorkflowStep | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


@dataclass
class WorkflowRun:
    """A single execution of a workflow."""
    run_id: str
    workflow_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.QUEUED
    steps: list[WorkflowStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    triggered_by: str = "manual"

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return 0

    @property
    def progress(self) -> dict[str, int]:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED))
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        running = sum(1 for s in self.steps if s.status == StepStatus.RUNNING)
        return {"total": total, "done": done, "failed": failed, "running": running}

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status.value,
            "progress": self.progress,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "triggered_by": self.triggered_by,
            "steps": [
                {
                    "id": s.id, "name": s.name, "type": s.type.value,
                    "status": s.status.value, "duration_ms": s.duration_ms,
                    "error": s.error, "attempts": s.attempts,
                }
                for s in self.steps
            ],
        }


StepExecutor = Callable[[WorkflowStep, dict[str, Any]], Awaitable[Any]]


_ALLOWED_AST_NODE_TYPES = frozenset({
    ast.Expression, ast.Compare, ast.Name, ast.Attribute, ast.Constant,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.BoolOp,
    ast.Subscript, ast.Index, ast.Load,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
})


def _safe_eval_condition(condition: str, context: dict[str, Any]) -> bool:
    """Safely evaluate a workflow condition expression using AST validation.

    Only allows: attribute access (ctx.foo), comparisons (==, !=, <, >, <=, >=),
    boolean operators (and, or, not), literals (str, int, float, bool, None),
    and subscript access (ctx['key']).

    Raises ValueError if the condition contains disallowed operations.
    """
    try:
        tree = ast.parse(condition.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid condition syntax: {exc}") from exc

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODE_TYPES:
            raise ValueError(
                f"Disallowed operation in condition: {type(node).__name__}. "
                f"Only comparisons, boolean ops, and attribute access are allowed."
            )

    compiled = compile(tree, filename="<workflow-condition>", mode="eval")
    return bool(eval(compiled, {"__builtins__": {}}, {"ctx": context}))


class WorkflowEngine:
    """Executes and manages workflow lifecycles."""

    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._step_executors: dict[StepType, StepExecutor] = {}
        self._listeners: list[Callable[[WorkflowRun], Awaitable[None]]] = []

    # -- registration --

    def register_workflow(self, definition: WorkflowDefinition) -> None:
        self._definitions[definition.id] = definition
        _log.info("Registered workflow: %s (%s)", definition.id, definition.name)

    def unregister_workflow(self, workflow_id: str) -> None:
        self._definitions.pop(workflow_id, None)

    def register_executor(self, step_type: StepType, executor: StepExecutor) -> None:
        self._step_executors[step_type] = executor

    def add_listener(self, listener: Callable[[WorkflowRun], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    # -- execution --

    async def start_workflow(
        self,
        workflow_id: str,
        context: dict[str, Any] | None = None,
        triggered_by: str = "manual",
    ) -> WorkflowRun:
        """Start a new workflow run."""
        defn = self._definitions.get(workflow_id)
        if defn is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        # Deep-copy steps so each run has independent state
        import copy
        steps = [copy.deepcopy(s) for s in defn.steps]

        run = WorkflowRun(
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_name=defn.name,
            steps=steps,
            context={**defn.variables, **(context or {})},
            triggered_by=triggered_by,
        )
        self._runs[run_id] = run

        # Execute in background
        task = asyncio.create_task(self._execute_run(run))
        self._active_tasks[run_id] = task
        return run

    async def cancel_run(self, run_id: str) -> bool:
        task = self._active_tasks.get(run_id)
        run = self._runs.get(run_id)
        if task and run:
            task.cancel()
            run.status = WorkflowStatus.CANCELLED
            run.finished_at = time.time()
            await self._notify(run)
            return True
        return False

    async def pause_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.status == WorkflowStatus.RUNNING:
            run.status = WorkflowStatus.PAUSED
            await self._notify(run)
            return True
        return False

    async def resume_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run and run.status == WorkflowStatus.PAUSED:
            run.status = WorkflowStatus.RUNNING
            await self._notify(run)
            return True
        return False

    # -- queries --

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._definitions.get(workflow_id)

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": d.id, "name": d.name, "description": d.description,
                "version": d.version, "steps": len(d.steps),
                "schedule": d.schedule, "tags": d.tags,
            }
            for d in self._definitions.values()
        ]

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._runs.get(run_id)

    def list_runs(
        self,
        workflow_id: str | None = None,
        status: WorkflowStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        runs = list(self._runs.values())
        if workflow_id:
            runs = [r for r in runs if r.workflow_id == workflow_id]
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.started_at or 0, reverse=True)
        return [r.to_summary() for r in runs[:limit]]

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for r in self._runs.values():
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        return {
            "total_workflows": len(self._definitions),
            "total_runs": len(self._runs),
            "active_runs": sum(1 for t in self._active_tasks.values() if not t.done()),
            "by_status": by_status,
        }

    # -- internal execution --

    async def _execute_run(self, run: WorkflowRun) -> None:
        run.status = WorkflowStatus.RUNNING
        run.started_at = time.time()
        await self._notify(run)

        try:
            completed: set[str] = set()
            while True:
                if run.status == WorkflowStatus.CANCELLED:
                    break
                # Wait while paused
                while run.status == WorkflowStatus.PAUSED:
                    await asyncio.sleep(0.5)

                # Find ready steps (all deps completed)
                ready = [
                    s for s in run.steps
                    if s.status == StepStatus.PENDING
                    and all(d in completed for d in s.depends_on)
                ]
                if not ready:
                    # Check if all done
                    pending = [s for s in run.steps if s.status == StepStatus.PENDING]
                    if not pending:
                        break
                    # Deadlock or waiting
                    failed = [s for s in run.steps if s.status == StepStatus.FAILED]
                    if failed:
                        break
                    await asyncio.sleep(0.1)
                    continue

                # Execute ready steps in parallel
                tasks = [
                    asyncio.create_task(self._execute_step(s, run))
                    for s in ready
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

                for s in ready:
                    if s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                        completed.add(s.id)

                await self._notify(run)

            # Determine final status
            failed = any(s.status == StepStatus.FAILED for s in run.steps)
            if run.status == WorkflowStatus.CANCELLED:
                pass
            elif failed:
                run.status = WorkflowStatus.FAILED
                run.error = "One or more steps failed"
            else:
                run.status = WorkflowStatus.SUCCESS

        except asyncio.CancelledError:
            run.status = WorkflowStatus.CANCELLED
        except Exception as exc:
            run.status = WorkflowStatus.FAILED
            run.error = str(exc)
            _log.exception("Workflow %s failed", run.run_id)
        finally:
            run.finished_at = time.time()
            self._active_tasks.pop(run.run_id, None)
            await self._notify(run)

    async def _execute_step(self, step: WorkflowStep, run: WorkflowRun) -> None:
        # Condition check
        if step.condition:
            try:
                if not _safe_eval_condition(step.condition, run.context):
                    step.status = StepStatus.SKIPPED
                    return
            except Exception:
                step.status = StepStatus.SKIPPED
                return

        executor = self._step_executors.get(step.type)
        if executor is None and step.type == StepType.DELAY:
            # Built-in delay
            step.status = StepStatus.RUNNING
            step.started_at = time.time()
            await asyncio.sleep(step.config.get("seconds", 1))
            step.status = StepStatus.SUCCESS
            step.finished_at = time.time()
            return

        if executor is None:
            step.status = StepStatus.FAILED
            step.error = f"No executor for step type: {step.type.value}"
            return

        max_attempts = step.retry_count + 1
        for attempt in range(max_attempts):
            step.attempts = attempt + 1
            step.status = StepStatus.RUNNING
            step.started_at = time.time()
            try:
                result = await asyncio.wait_for(
                    executor(step, run.context),
                    timeout=step.timeout_s,
                )
                step.output = result
                step.status = StepStatus.SUCCESS
                step.finished_at = time.time()
                # Pass output to context for downstream steps
                run.context[f"step_{step.id}_output"] = result
                return
            except asyncio.TimeoutError:
                step.status = StepStatus.TIMEOUT
                step.error = f"Timeout after {step.timeout_s}s"
                step.finished_at = time.time()
            except Exception as exc:
                step.status = StepStatus.FAILED
                step.error = str(exc)
                step.finished_at = time.time()
                if attempt < max_attempts - 1:
                    _log.warning("Step %s attempt %d failed, retrying: %s", step.id, attempt + 1, exc)
                    await asyncio.sleep(1)

    async def _notify(self, run: WorkflowRun) -> None:
        for listener in self._listeners:
            try:
                await listener(run)
            except Exception:
                pass
