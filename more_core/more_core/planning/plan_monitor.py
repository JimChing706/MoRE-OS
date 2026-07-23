"""L5 Plan Monitor — metacognitive adaptive monitoring of plan execution.

Provides real-time monitoring of plan execution with adaptive interventions:
- Budget burn-rate analysis → dynamic reallocation
- Step failure pattern detection → circuit-breaking or plan revision
- Confidence drift detection → triggers re-calibration
- Automatic plan adjustments when execution deviates from expectations
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from .coordinator import ExecutionPlan, PlanStep, PlanStatus, StepPriority

_log = logging.getLogger(__name__)


class AdaptiveAction(Enum):
    """Actions the monitor can take in response to observations."""

    NONE = "none"
    REALLOCATE_BUDGET = "reallocate_budget"
    SKIP_LOW_PRIORITY = "skip_low_priority"
    REDUCE_MAX_TOKENS = "reduce_max_tokens"
    INCREASE_TIMEOUT = "increase_timeout"
    PAUSE_PLAN = "pause_plan"
    ABORT_PLAN = "abort_plan"


@dataclass
class MonitoringEvent:
    """A single monitoring observation with timestamp."""

    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    plan_id: str = ""
    step_id: str = ""
    metric: str = ""
    value: float = 0.0
    threshold: float = 0.0
    action_taken: AdaptiveAction = AdaptiveAction.NONE
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanHealthReport:
    """Health assessment of a running plan."""

    plan_id: str
    status: str
    progress_pct: float
    budget_burn_rate: float  # tokens consumed per % progress
    estimated_tokens_at_completion: int
    budget_will_exceed: bool
    consecutive_failures: int
    confidence_trend: str  # "stable", "improving", "degrading"
    recommended_actions: list[AdaptiveAction]
    step_details: list[dict[str, Any]]


class PlanMonitor:
    """L5 metacognitive monitor for plan execution.

    Continuously observes plan progress and makes adaptive decisions:

    1. **Budget tracking**: Detects over-spending early, reallocates tokens
    2. **Failure patterns**: Consecutive failures trigger plan revision
    3. **Confidence drift**: Watches calibration alignment over time
    4. **Adaptive interventions**: Automatically adjusts plan parameters
    """

    # Thresholds
    BUDGET_OVERRUN_THRESHOLD = 1.3  # 130% of predicted = warning
    FAILURE_STREAK_LIMIT = 2  # Consecutive failures before intervention
    CONFIDENCE_FLOOR = 0.4  # Below this → pause for review
    BURN_RATE_CEILING = 200.0  # tokens per 1% progress threshold

    def __init__(self) -> None:
        self._events: list[MonitoringEvent] = []
        self._confidence_history: deque[float] = deque(maxlen=500)
        self._on_action_callbacks: list[
            Callable[[AdaptiveAction, ExecutionPlan, dict[str, Any]], Awaitable[None]]
        ] = []

    def register_callback(
        self, callback: Callable[[AdaptiveAction, ExecutionPlan, dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Register a callback for when the monitor takes an adaptive action."""
        self._on_action_callbacks.append(callback)

    def observe_step_completion(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        confidence: float = 0.8,
    ) -> list[AdaptiveAction]:
        """Observe a step completion and decide on adaptive actions.

        Called after each step finishes (success or failure).
        Returns list of adaptive actions recommended/taken.
        """
        self._confidence_history.append(confidence)
        actions: list[AdaptiveAction] = []

        # --- Budget burn-rate analysis ---
        burn_rate = self._calculate_burn_rate(plan)
        if burn_rate > self.BURN_RATE_CEILING and plan.progress_pct < 70:
            actions.append(AdaptiveAction.REALLOCATE_BUDGET)
            self._record_event(
                plan,
                step,
                "budget_overrun",
                burn_rate,
                self.BURN_RATE_CEILING,
                AdaptiveAction.REALLOCATE_BUDGET,
            )
            _log.warning(
                "Plan %s: burn rate %.1f tokens/pct exceeds ceiling %.1f",
                plan.id,
                burn_rate,
                self.BURN_RATE_CEILING,
            )

        # --- Failure pattern detection ---
        consecutive_failures = self._count_consecutive_failures(plan)
        if consecutive_failures >= self.FAILURE_STREAK_LIMIT:
            critical_failed = any(
                s.status == PlanStatus.FAILED and s.priority == StepPriority.CRITICAL
                for s in plan.steps
            )
            if critical_failed:
                actions.append(AdaptiveAction.ABORT_PLAN)
                self._record_event(
                    plan,
                    step,
                    "critical_failure_streak",
                    consecutive_failures,
                    self.FAILURE_STREAK_LIMIT,
                    AdaptiveAction.ABORT_PLAN,
                )
            else:
                actions.append(AdaptiveAction.SKIP_LOW_PRIORITY)
                self._record_event(
                    plan,
                    step,
                    "failure_streak",
                    consecutive_failures,
                    self.FAILURE_STREAK_LIMIT,
                    AdaptiveAction.SKIP_LOW_PRIORITY,
                )

        # --- Confidence drift detection ---
        if len(self._confidence_history) >= 3:
            recent = list(self._confidence_history)[-3:]
            recent_avg = sum(recent) / 3
            if recent_avg < self.CONFIDENCE_FLOOR:
                actions.append(AdaptiveAction.PAUSE_PLAN)
                self._record_event(
                    plan,
                    step,
                    "confidence_drop",
                    recent_avg,
                    self.CONFIDENCE_FLOOR,
                    AdaptiveAction.PAUSE_PLAN,
                )
                _log.warning(
                    "Plan %s: confidence dropped to %.2f, recommending pause", plan.id, recent_avg
                )

        # --- Over-budget projection ---
        if plan.progress_pct > 20:
            projected = self._project_total_tokens(plan)
            if projected > plan.max_total_tokens * self.BUDGET_OVERRUN_THRESHOLD:
                actions.append(AdaptiveAction.REDUCE_MAX_TOKENS)
                self._record_event(
                    plan,
                    step,
                    "projected_overrun",
                    projected,
                    plan.max_total_tokens,
                    AdaptiveAction.REDUCE_MAX_TOKENS,
                )

        return actions

    def apply_adaptive_actions(
        self,
        plan: ExecutionPlan,
        actions: list[AdaptiveAction],
    ) -> dict[str, Any]:
        """Apply adaptive actions to modify the plan in-flight.

        Returns a summary of modifications made.
        """
        modifications: dict[str, Any] = {"actions_applied": []}

        for action in actions:
            if action == AdaptiveAction.REALLOCATE_BUDGET:
                # Reduce token budget for remaining low-priority steps
                remaining = [s for s in plan.steps if s.status == PlanStatus.DRAFT]
                for s in remaining:
                    if s.priority in (StepPriority.LOW, StepPriority.NORMAL):
                        s.estimated_tokens = int(s.estimated_tokens * 0.7)
                modifications["budget_reduced_steps"] = len(remaining)

            elif action == AdaptiveAction.SKIP_LOW_PRIORITY:
                # Mark remaining LOW priority steps as skipped
                skipped = 0
                for s in plan.steps:
                    if s.status == PlanStatus.DRAFT and s.priority == StepPriority.LOW:
                        s.status = PlanStatus.COMPLETED
                        s.output = "[skipped by monitor: failure streak]"
                        skipped += 1
                modifications["skipped_steps"] = skipped

            elif action == AdaptiveAction.REDUCE_MAX_TOKENS:
                # Reduce remaining step token budgets by 30%
                remaining = [s for s in plan.steps if s.status == PlanStatus.DRAFT]
                for s in remaining:
                    s.estimated_tokens = max(256, int(s.estimated_tokens * 0.7))
                modifications["tokens_reduced_for"] = len(remaining)

            elif action == AdaptiveAction.PAUSE_PLAN:
                plan.status = PlanStatus.CHECKPOINT
                modifications["paused"] = True

            elif action == AdaptiveAction.ABORT_PLAN:
                plan.status = PlanStatus.FAILED
                modifications["aborted"] = True

            modifications["actions_applied"].append(action.value)

        return modifications

    def get_health_report(self, plan: ExecutionPlan) -> PlanHealthReport:
        """Generate a comprehensive health report for a plan."""
        burn_rate = self._calculate_burn_rate(plan)
        projected = self._project_total_tokens(plan)
        consecutive_failures = self._count_consecutive_failures(plan)

        # Confidence trend
        if len(self._confidence_history) >= 5:
            history_list = list(self._confidence_history)
            early = sum(history_list[:3]) / 3
            late = sum(history_list[-3:]) / 3
            if late > early + 0.05:
                trend = "improving"
            elif late < early - 0.05:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Recommended actions
        recommended: list[AdaptiveAction] = []
        if projected > plan.max_total_tokens:
            recommended.append(AdaptiveAction.REALLOCATE_BUDGET)
        if consecutive_failures >= self.FAILURE_STREAK_LIMIT:
            recommended.append(AdaptiveAction.SKIP_LOW_PRIORITY)

        step_details = [
            {
                "id": s.id,
                "status": s.status.value,
                "priority": s.priority.value,
                "estimated_tokens": s.estimated_tokens,
                "actual_tokens": s.actual_tokens,
                "efficiency": (
                    round(s.actual_tokens / s.estimated_tokens, 2)
                    if s.estimated_tokens > 0 and s.actual_tokens > 0
                    else None
                ),
            }
            for s in plan.steps
        ]

        return PlanHealthReport(
            plan_id=plan.id,
            status=plan.status.value,
            progress_pct=plan.progress_pct,
            budget_burn_rate=burn_rate,
            estimated_tokens_at_completion=projected,
            budget_will_exceed=projected > plan.max_total_tokens,
            consecutive_failures=consecutive_failures,
            confidence_trend=trend,
            recommended_actions=recommended,
            step_details=step_details,
        )

    def get_events(self, plan_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get monitoring events, optionally filtered by plan."""
        events = self._events
        if plan_id:
            events = [e for e in events if e.plan_id == plan_id]
        return [
            {
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "plan_id": e.plan_id,
                "step_id": e.step_id,
                "metric": e.metric,
                "value": e.value,
                "threshold": e.threshold,
                "action": e.action_taken.value,
            }
            for e in events[-limit:]
        ]

    # --- Internal helpers ---

    def _calculate_burn_rate(self, plan: ExecutionPlan) -> float:
        """Tokens consumed per 1% of progress."""
        if plan.progress_pct <= 0:
            return 0.0
        return plan.tokens_used / plan.progress_pct

    def _project_total_tokens(self, plan: ExecutionPlan) -> int:
        """Project total token consumption at completion based on current rate."""
        if plan.progress_pct <= 0:
            return sum(s.estimated_tokens for s in plan.steps)
        return int(plan.tokens_used / (plan.progress_pct / 100.0))

    def _count_consecutive_failures(self, plan: ExecutionPlan) -> int:
        """Count consecutive failed steps from the most recent completed."""
        count = 0
        for step in reversed(plan.steps):
            if step.status == PlanStatus.FAILED:
                count += 1
            elif step.status == PlanStatus.COMPLETED:
                break
            # Skip DRAFT steps (not yet executed)
        return count

    def _record_event(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
        event_type: str,
        value: float,
        threshold: float,
        action: AdaptiveAction,
    ) -> None:
        self._events.append(
            MonitoringEvent(
                event_type=event_type,
                plan_id=plan.id,
                step_id=step.id,
                metric=event_type,
                value=value,
                threshold=threshold,
                action_taken=action,
            )
        )
