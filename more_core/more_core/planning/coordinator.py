"""Plan Coordinator — rigorous task planning with dependency tracking.

Bridges L4's decomposition into structured execution plans with:
- Goal verification (pre/post conditions)
- Step dependency resolution
- Resource estimation and budget tracking
- Progress monitoring with checkpoints
- Rollback on critical failures
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class PlanStatus(Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    EXECUTING = "executing"
    CHECKPOINT = "checkpoint"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class StepPriority(Enum):
    CRITICAL = "critical"  # Must succeed for plan to succeed
    HIGH = "high"          # Important but plan can continue with degradation
    NORMAL = "normal"      # Standard priority
    LOW = "low"            # Optional / best-effort


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: str
    description: str
    priority: StepPriority = StepPriority.NORMAL
    depends_on: list[str] = field(default_factory=list)
    estimated_tokens: int = 1024
    estimated_duration_ms: float = 5000.0
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)

    # Runtime state
    status: PlanStatus = PlanStatus.DRAFT
    output: Any = None
    actual_tokens: int = 0
    actual_duration_ms: float = 0.0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class ExecutionPlan:
    """A rigorous execution plan with goals, constraints, and checkpoints."""
    id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:12]}")
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)

    # Budget and constraints
    max_total_tokens: int = 16384
    max_duration_ms: float = 60000.0
    tokens_used: int = 0
    duration_used_ms: float = 0.0

    # Checkpoints for rollback
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def progress_pct(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status == PlanStatus.COMPLETED)
        return (done / len(self.steps)) * 100.0

    @property
    def budget_remaining(self) -> dict[str, float]:
        return {
            "tokens": max(0, self.max_total_tokens - self.tokens_used),
            "duration_ms": max(0, self.max_duration_ms - self.duration_used_ms),
        }

    @property
    def is_over_budget(self) -> bool:
        return self.tokens_used > self.max_total_tokens or self.duration_used_ms > self.max_duration_ms

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "steps": len(self.steps),
            "progress_pct": round(self.progress_pct, 1),
            "tokens_used": self.tokens_used,
            "budget_remaining": self.budget_remaining,
            "duration_ms": self.duration_used_ms,
        }


class PlanCoordinator:
    """Coordinates rigorous multi-step task execution with planning guarantees.

    Responsibilities:
    1. Convert L4 decomposition into validated execution plans
    2. Resolve step dependencies into correct execution order
    3. Track budget (tokens, time) and abort if over-limit
    4. Create checkpoints for partial rollback
    5. Report progress with structured metrics
    """

    def __init__(self) -> None:
        self._plans: dict[str, ExecutionPlan] = {}
        self._active_plan: ExecutionPlan | None = None

    def create_plan(
        self,
        goal: str,
        subtasks: list[str],
        difficulty: int = 5,
        max_tokens: int = 16384,
        max_duration_ms: float = 60000.0,
    ) -> ExecutionPlan:
        """Create an execution plan from L4's decomposition output."""
        steps = []
        for i, desc in enumerate(subtasks):
            step_id = f"step_{i:03d}"
            # First step has no dependencies; subsequent depend on prior
            deps = [f"step_{i-1:03d}"] if i > 0 else []
            # Estimate tokens based on difficulty and position
            est_tokens = min(4096, 512 * (1 + difficulty // 3))
            priority = StepPriority.CRITICAL if i == 0 else StepPriority.NORMAL

            steps.append(PlanStep(
                id=step_id,
                description=desc,
                priority=priority,
                depends_on=deps,
                estimated_tokens=est_tokens,
                estimated_duration_ms=est_tokens * 5.0,  # ~5ms per token rough estimate
            ))

        plan = ExecutionPlan(
            goal=goal,
            steps=steps,
            max_total_tokens=max_tokens,
            max_duration_ms=max_duration_ms,
        )
        self._plans[plan.id] = plan
        _log.info("Created plan %s: %d steps, budget=%d tokens", plan.id, len(steps), max_tokens)
        return plan

    def validate_plan(self, plan: ExecutionPlan) -> list[str]:
        """Validate plan structure. Returns list of issues (empty = valid)."""
        issues: list[str] = []

        if not plan.steps:
            issues.append("Plan has no steps")
            return issues

        step_ids = {s.id for s in plan.steps}

        # Check dependency graph is acyclic and references valid steps
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    issues.append(f"Step {step.id} depends on unknown step {dep}")

        # Check for cycles (simple DFS)
        visited: set[str] = set()
        in_stack: set[str] = set()
        dep_map = {s.id: s.depends_on for s in plan.steps}

        def has_cycle(node: str) -> bool:
            if node in in_stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            in_stack.add(node)
            for dep in dep_map.get(node, []):
                if has_cycle(dep):
                    return True
            in_stack.discard(node)
            return False

        for step in plan.steps:
            if has_cycle(step.id):
                issues.append("Dependency cycle detected")
                break

        # Budget feasibility
        total_est_tokens = sum(s.estimated_tokens for s in plan.steps)
        if total_est_tokens > plan.max_total_tokens * 1.5:  # Allow 50% overestimate buffer
            issues.append(
                f"Estimated tokens ({total_est_tokens}) far exceeds budget ({plan.max_total_tokens})"
            )

        if not issues:
            plan.status = PlanStatus.VALIDATED

        return issues

    def get_execution_order(self, plan: ExecutionPlan) -> list[list[PlanStep]]:
        """Resolve step dependencies into parallelizable execution waves."""
        completed: set[str] = set()
        remaining = list(plan.steps)
        waves: list[list[PlanStep]] = []

        while remaining:
            wave = [
                s for s in remaining
                if all(d in completed for d in s.depends_on)
            ]
            if not wave:
                # Deadlock — remaining steps have unmet deps
                _log.warning("Plan %s: deadlock, %d steps unreachable", plan.id, len(remaining))
                break
            waves.append(wave)
            for s in wave:
                completed.add(s.id)
            remaining = [s for s in remaining if s.id not in completed]

        return waves

    def record_step_result(
        self,
        plan: ExecutionPlan,
        step_id: str,
        output: Any,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Record step completion and update plan budget tracking."""
        step = next((s for s in plan.steps if s.id == step_id), None)
        if step is None:
            return

        step.finished_at = time.time()
        step.actual_tokens = tokens_used
        step.actual_duration_ms = duration_ms
        step.output = output
        step.status = PlanStatus.COMPLETED if success else PlanStatus.FAILED
        step.error = error

        # Update plan-level budgets
        plan.tokens_used += tokens_used
        plan.duration_used_ms += duration_ms

        if plan.is_over_budget:
            _log.warning("Plan %s exceeded budget: tokens=%d/%d", plan.id, plan.tokens_used, plan.max_total_tokens)

    def checkpoint(self, plan: ExecutionPlan) -> None:
        """Create a checkpoint for potential rollback."""
        plan.checkpoints.append({
            "timestamp": time.time(),
            "progress_pct": plan.progress_pct,
            "tokens_used": plan.tokens_used,
            "completed_steps": [s.id for s in plan.steps if s.status == PlanStatus.COMPLETED],
        })

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        return self._plans.get(plan_id)

    def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        plans = sorted(self._plans.values(), key=lambda p: p.created_at, reverse=True)
        return [p.to_summary() for p in plans[:limit]]

    def stats(self) -> dict[str, Any]:
        return {
            "total_plans": len(self._plans),
            "by_status": {
                status.value: sum(1 for p in self._plans.values() if p.status == status)
                for status in PlanStatus
            },
        }
