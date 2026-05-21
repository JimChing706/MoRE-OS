"""Plan→Workflow Bridge — auto-converts ExecutionPlans into WorkflowDefinitions.

This bridge enables seamless integration between the PlanCoordinator
(rigorous planning) and the WorkflowEngine (DAG execution runtime):

1. Converts PlanStep dependencies to WorkflowStep DAG
2. Maps priority levels to retry/timeout policies
3. Injects token budget into step config for monitoring
4. Synchronizes workflow execution results back to the plan
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .coordinator import ExecutionPlan, PlanStatus, StepPriority
from .token_predictor import TokenPredictor, TokenObservation

if TYPE_CHECKING:
    from ..workflows.engine import (
        WorkflowDefinition,
        WorkflowStep,
        WorkflowRun,
        WorkflowEngine,
    )

_log = logging.getLogger(__name__)


# Priority → (timeout_s, retry_count) mapping
_PRIORITY_POLICIES: dict[StepPriority, tuple[int, int]] = {
    StepPriority.CRITICAL: (120, 2),
    StepPriority.HIGH: (90, 1),
    StepPriority.NORMAL: (60, 0),
    StepPriority.LOW: (30, 0),
}


class PlanWorkflowBridge:
    """Bridges PlanCoordinator ↔ WorkflowEngine with token prediction.

    Lifecycle:
    1. plan_to_workflow() — converts a validated plan into a workflow definition
    2. start_plan_workflow() — registers + starts the workflow
    3. sync_results() — propagates workflow step results back into the plan
    """

    def __init__(
        self,
        workflow_engine: "WorkflowEngine",
        token_predictor: TokenPredictor | None = None,
    ) -> None:
        self._engine = workflow_engine
        self._predictor = token_predictor or TokenPredictor()
        self._plan_run_map: dict[str, str] = {}  # plan_id → run_id
        self._run_plan_map: dict[str, str] = {}  # run_id → plan_id

    @property
    def predictor(self) -> TokenPredictor:
        return self._predictor

    def plan_to_workflow(
        self,
        plan: ExecutionPlan,
        task_type: str = "nlp_task",
    ) -> "WorkflowDefinition":
        """Convert an ExecutionPlan into a WorkflowDefinition.

        Each PlanStep becomes a WorkflowStep of type TASK with:
        - Dependency mapping preserved
        - Token budget injected into config
        - Timeout/retry derived from priority
        """
        from ..workflows.engine import WorkflowDefinition, WorkflowStep, StepType

        # Predict token allocations
        subtask_descs = [s.description for s in plan.steps]
        difficulty = plan.context.get("difficulty", 5)
        predictions = self._predictor.predict_plan_total(
            task_type=task_type,
            subtasks=subtask_descs,
            difficulty=difficulty,
        )
        allocations = self._predictor.allocate_budget(
            total_budget=plan.max_total_tokens,
            predictions=predictions,
        )

        workflow_steps: list[WorkflowStep] = []
        for i, step in enumerate(plan.steps):
            timeout_s, retry_count = _PRIORITY_POLICIES.get(
                step.priority, (60, 0)
            )
            token_budget = allocations[i] if i < len(allocations) else step.estimated_tokens

            wf_step = WorkflowStep(
                id=step.id,
                name=step.description[:80],
                type=StepType.TASK,
                config={
                    "query": step.description,
                    "task_type": task_type,
                    "token_budget": token_budget,
                    "predicted_tokens": predictions[i] if i < len(predictions) else 0,
                    "priority": step.priority.value,
                    "plan_step_id": step.id,
                },
                depends_on=list(step.depends_on),
                timeout_s=timeout_s,
                retry_count=retry_count,
            )
            workflow_steps.append(wf_step)

        workflow_id = f"plan_wf_{plan.id}"
        definition = WorkflowDefinition(
            id=workflow_id,
            name=f"Plan: {plan.goal[:60]}",
            description=f"Auto-generated workflow from plan {plan.id}",
            steps=workflow_steps,
            variables={
                "plan_id": plan.id,
                "goal": plan.goal,
                "total_token_budget": plan.max_total_tokens,
                "difficulty": difficulty,
            },
            tags=["auto_plan", task_type],
        )

        _log.info(
            "Converted plan %s → workflow %s (%d steps, budget=%d tokens)",
            plan.id, workflow_id, len(workflow_steps), plan.max_total_tokens,
        )
        return definition

    async def start_plan_workflow(
        self,
        plan: ExecutionPlan,
        task_type: str = "nlp_task",
    ) -> "WorkflowRun":
        """Convert plan to workflow, register, and start execution."""
        definition = self.plan_to_workflow(plan, task_type)
        self._engine.register_workflow(definition)

        run = await self._engine.start_workflow(
            workflow_id=definition.id,
            context={"plan_id": plan.id},
            triggered_by="plan_coordinator",
        )

        self._plan_run_map[plan.id] = run.run_id
        self._run_plan_map[run.run_id] = plan.id
        plan.status = PlanStatus.EXECUTING

        return run

    def sync_results(
        self,
        plan: ExecutionPlan,
        run: "WorkflowRun",
    ) -> None:
        """Synchronize workflow run results back into the plan.

        Updates plan step statuses, actual token usage, and
        feeds observations into the token predictor for learning.
        """
        from ..workflows.engine import StepStatus

        for wf_step in run.steps:
            plan_step = next(
                (s for s in plan.steps if s.id == wf_step.id), None
            )
            if plan_step is None:
                continue

            # Map workflow status → plan status
            if wf_step.status == StepStatus.SUCCESS:
                plan_step.status = PlanStatus.COMPLETED
                plan_step.output = wf_step.output
            elif wf_step.status in (StepStatus.FAILED, StepStatus.TIMEOUT):
                plan_step.status = PlanStatus.FAILED
                plan_step.error = wf_step.error
            else:
                continue  # Still pending/running

            plan_step.actual_duration_ms = wf_step.duration_ms
            plan_step.finished_at = wf_step.finished_at

            # Extract actual token usage from step output if available
            actual_tokens = 0
            if isinstance(wf_step.output, dict):
                actual_tokens = wf_step.output.get("tokens_used", 0)
            elif isinstance(wf_step.output, str):
                # Rough estimate: ~0.75 tokens per character for English
                actual_tokens = int(len(wf_step.output) * 0.75)

            plan_step.actual_tokens = actual_tokens
            plan.tokens_used += actual_tokens
            plan.duration_used_ms += wf_step.duration_ms

            # Feed back to predictor for learning
            config = wf_step.config or {}
            self._predictor.observe(TokenObservation(
                task_type=config.get("task_type", "nlp_task"),
                query_length=len(config.get("query", "")),
                estimated_tokens=config.get("predicted_tokens", 0),
                actual_tokens=actual_tokens,
                difficulty=run.context.get("difficulty", 5),
                timestamp=time.time(),
            ))

        # Update plan-level status
        all_done = all(
            s.status in (PlanStatus.COMPLETED, PlanStatus.FAILED)
            for s in plan.steps
        )
        if all_done:
            any_failed = any(
                s.status == PlanStatus.FAILED and s.priority == StepPriority.CRITICAL
                for s in plan.steps
            )
            plan.status = PlanStatus.FAILED if any_failed else PlanStatus.COMPLETED

    def get_run_for_plan(self, plan_id: str) -> str | None:
        """Get workflow run_id associated with a plan."""
        return self._plan_run_map.get(plan_id)

    def get_plan_for_run(self, run_id: str) -> str | None:
        """Get plan_id associated with a workflow run."""
        return self._run_plan_map.get(run_id)
