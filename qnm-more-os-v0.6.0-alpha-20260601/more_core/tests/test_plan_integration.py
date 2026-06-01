"""Tests for Plan→Workflow integration, Token Predictor, and L5 Plan Monitor.

Covers:
1. TokenPredictor: prediction, EMA learning, budget allocation
2. PlanWorkflowBridge: plan→workflow conversion, result sync
3. PlanMonitor: burn-rate detection, failure streaks, adaptive actions, health reports
4. L5 MetacognitionLayer: plan monitoring integration
"""

import asyncio
import pytest
import time

from more_core.planning.coordinator import (
    PlanCoordinator,
    ExecutionPlan,
    PlanStep,
    PlanStatus,
    StepPriority,
)
from more_core.planning.token_predictor import TokenPredictor, TokenObservation
from more_core.planning.workflow_bridge import PlanWorkflowBridge
from more_core.planning.plan_monitor import (
    PlanMonitor,
    AdaptiveAction,
    PlanHealthReport,
)
from more_core.workflows.engine import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowRun,
    StepType,
    StepStatus,
    WorkflowStatus,
)


# =========================================================================
# TokenPredictor Tests
# =========================================================================


class TestTokenPredictor:

    def test_predict_basic(self):
        tp = TokenPredictor()
        tokens = tp.predict(task_type="code_generation", query_length=100, difficulty=5)
        assert 256 <= tokens <= 8192

    def test_predict_difficulty_scaling(self):
        tp = TokenPredictor()
        low = tp.predict(task_type="nlp_task", query_length=50, difficulty=1)
        high = tp.predict(task_type="nlp_task", query_length=50, difficulty=10)
        assert high > low, "Higher difficulty should predict more tokens"

    def test_predict_position_scaling(self):
        tp = TokenPredictor()
        first = tp.predict("nlp_task", 50, difficulty=5, step_index=0, total_steps=5)
        last = tp.predict("nlp_task", 50, difficulty=5, step_index=4, total_steps=5)
        assert last > first, "Later steps should predict more tokens"

    def test_predict_unknown_task_type(self):
        tp = TokenPredictor()
        tokens = tp.predict(task_type="unknown_type", query_length=100, difficulty=5)
        assert 256 <= tokens <= 8192  # Should use fallback base of 1024

    def test_predict_plan_total(self):
        tp = TokenPredictor()
        predictions = tp.predict_plan_total(
            task_type="code_generation",
            subtasks=["Write auth module", "Add tests", "Deploy"],
            difficulty=7,
        )
        assert len(predictions) == 3
        assert all(256 <= p <= 8192 for p in predictions)

    def test_observe_adjusts_ema(self):
        tp = TokenPredictor()
        # Observe consistent under-prediction (actual > estimated)
        for _ in range(10):
            tp.observe(TokenObservation(
                task_type="nlp_task", query_length=50,
                estimated_tokens=500, actual_tokens=800,
                difficulty=5, timestamp=time.time(),
            ))
        assert tp._ema_error > 0, "EMA should shift positive when under-predicting"

        # Future predictions should be corrected upward
        before = TokenPredictor().predict("nlp_task", 50, 5)
        after = tp.predict("nlp_task", 50, 5)
        assert after > before

    def test_observe_over_prediction(self):
        tp = TokenPredictor()
        for _ in range(10):
            tp.observe(TokenObservation(
                task_type="nlp_task", query_length=50,
                estimated_tokens=1000, actual_tokens=400,
                difficulty=5, timestamp=time.time(),
            ))
        assert tp._ema_error < 0, "EMA should shift negative when over-predicting"

    def test_allocate_budget_under(self):
        tp = TokenPredictor()
        predictions = [500, 500, 500]
        allocations = tp.allocate_budget(total_budget=3000, predictions=predictions)
        assert len(allocations) == 3
        # Surplus of 1500 should be distributed, weighted toward later steps
        assert allocations[2] > allocations[0]

    def test_allocate_budget_over(self):
        tp = TokenPredictor()
        predictions = [2000, 2000, 2000]
        allocations = tp.allocate_budget(total_budget=3000, predictions=predictions)
        assert sum(allocations) <= 3000
        assert all(a >= 256 for a in allocations)  # Minimum floor respected

    def test_allocate_budget_empty(self):
        tp = TokenPredictor()
        assert tp.allocate_budget(1000, []) == []

    def test_accuracy_stats_empty(self):
        tp = TokenPredictor()
        stats = tp.get_accuracy_stats()
        assert stats["observations"] == 0
        assert stats["mean_error_pct"] == 0.0

    def test_accuracy_stats_with_data(self):
        tp = TokenPredictor()
        tp.observe(TokenObservation("nlp_task", 50, 1000, 1200, 5, time.time()))
        tp.observe(TokenObservation("nlp_task", 50, 1000, 800, 5, time.time()))
        stats = tp.get_accuracy_stats()
        assert stats["observations"] == 2
        assert stats["mean_error_pct"] > 0


# =========================================================================
# PlanWorkflowBridge Tests
# =========================================================================


class TestPlanWorkflowBridge:

    def _make_bridge(self):
        engine = WorkflowEngine()
        predictor = TokenPredictor()
        return PlanWorkflowBridge(engine, predictor), engine

    def test_plan_to_workflow_basic(self):
        bridge, engine = self._make_bridge()
        coordinator = PlanCoordinator()
        plan = coordinator.create_plan(
            goal="Build feature X",
            subtasks=["Design API", "Implement", "Test"],
            difficulty=6,
            max_tokens=10000,
        )
        plan.context["difficulty"] = 6

        wf = bridge.plan_to_workflow(plan, task_type="code_generation")
        assert isinstance(wf, WorkflowDefinition)
        assert len(wf.steps) == 3
        assert wf.id == f"plan_wf_{plan.id}"
        assert "auto_plan" in wf.tags
        assert wf.variables["plan_id"] == plan.id

    def test_plan_to_workflow_preserves_dependencies(self):
        bridge, _ = self._make_bridge()
        plan = ExecutionPlan(
            goal="Dep test",
            steps=[
                PlanStep(id="a", description="Step A"),
                PlanStep(id="b", description="Step B", depends_on=["a"]),
                PlanStep(id="c", description="Step C", depends_on=["a", "b"]),
            ],
            max_total_tokens=8000,
        )
        wf = bridge.plan_to_workflow(plan)
        step_b = next(s for s in wf.steps if s.id == "b")
        step_c = next(s for s in wf.steps if s.id == "c")
        assert step_b.depends_on == ["a"]
        assert step_c.depends_on == ["a", "b"]

    def test_plan_to_workflow_priority_policies(self):
        bridge, _ = self._make_bridge()
        plan = ExecutionPlan(
            goal="Priority test",
            steps=[
                PlanStep(id="crit", description="Critical step", priority=StepPriority.CRITICAL),
                PlanStep(id="low", description="Low step", priority=StepPriority.LOW),
            ],
            max_total_tokens=8000,
        )
        wf = bridge.plan_to_workflow(plan)
        crit_step = next(s for s in wf.steps if s.id == "crit")
        low_step = next(s for s in wf.steps if s.id == "low")
        assert crit_step.timeout_s == 120
        assert crit_step.retry_count == 2
        assert low_step.timeout_s == 30
        assert low_step.retry_count == 0

    def test_plan_to_workflow_injects_token_budget(self):
        bridge, _ = self._make_bridge()
        coordinator = PlanCoordinator()
        plan = coordinator.create_plan(
            goal="Token budget test",
            subtasks=["Single step"],
            difficulty=5,
            max_tokens=5000,
        )
        plan.context["difficulty"] = 5
        wf = bridge.plan_to_workflow(plan)
        assert wf.steps[0].config["token_budget"] > 0
        assert wf.steps[0].config["predicted_tokens"] > 0

    @pytest.mark.asyncio
    async def test_start_plan_workflow(self):
        bridge, engine = self._make_bridge()
        coordinator = PlanCoordinator()
        plan = coordinator.create_plan(
            goal="Start test",
            subtasks=["Step 1"],
            difficulty=5,
            max_tokens=5000,
        )
        plan.context["difficulty"] = 5
        # Register a dummy executor so the step can run
        async def dummy_exec(step, ctx):
            return "done"
        engine.register_executor(StepType.TASK, dummy_exec)

        run = await bridge.start_plan_workflow(plan)
        assert run.run_id.startswith("run_")
        assert plan.status == PlanStatus.EXECUTING
        assert bridge.get_run_for_plan(plan.id) == run.run_id
        assert bridge.get_plan_for_run(run.run_id) == plan.id
        # Let async task finish
        await asyncio.sleep(0.3)

    def test_sync_results_success(self):
        bridge, _ = self._make_bridge()
        plan = ExecutionPlan(
            goal="Sync test",
            steps=[
                PlanStep(id="s1", description="Step 1", estimated_tokens=1000),
                PlanStep(id="s2", description="Step 2", estimated_tokens=1000),
            ],
            max_total_tokens=5000,
        )
        # Simulate a completed workflow run
        run = WorkflowRun(
            run_id="r1",
            workflow_id="wf1",
            workflow_name="test",
            status=WorkflowStatus.SUCCESS,
            steps=[
                WorkflowStep(
                    id="s1", name="Step 1", type=StepType.TASK,
                    status=StepStatus.SUCCESS, output="result_1",
                    started_at=1.0, finished_at=1.5,
                    config={"task_type": "nlp_task", "query": "Step 1", "predicted_tokens": 1000},
                ),
                WorkflowStep(
                    id="s2", name="Step 2", type=StepType.TASK,
                    status=StepStatus.FAILED, error="timeout",
                    started_at=2.0, finished_at=2.8,
                    config={"task_type": "nlp_task", "query": "Step 2", "predicted_tokens": 1000},
                ),
            ],
            context={"difficulty": 5},
        )
        bridge.sync_results(plan, run)
        assert plan.steps[0].status == PlanStatus.COMPLETED
        assert plan.steps[0].output == "result_1"
        assert plan.steps[1].status == PlanStatus.FAILED
        assert plan.steps[1].error == "timeout"
        assert plan.tokens_used > 0
        assert plan.duration_used_ms > 0

    def test_sync_results_updates_predictor(self):
        bridge, _ = self._make_bridge()
        plan = ExecutionPlan(
            goal="Learning test",
            steps=[PlanStep(id="s1", description="Step 1", estimated_tokens=500)],
            max_total_tokens=5000,
        )
        run = WorkflowRun(
            run_id="r1", workflow_id="wf1", workflow_name="test",
            status=WorkflowStatus.SUCCESS,
            steps=[
                WorkflowStep(
                    id="s1", name="Step 1", type=StepType.TASK,
                    status=StepStatus.SUCCESS, output={"tokens_used": 750},
                    started_at=1.0, finished_at=1.3,
                    config={"task_type": "nlp_task", "query": "Step 1", "predicted_tokens": 500},
                ),
            ],
            context={"difficulty": 5},
        )
        bridge.sync_results(plan, run)
        stats = bridge.predictor.get_accuracy_stats()
        assert stats["observations"] == 1

    def test_sync_results_plan_completion_status(self):
        bridge, _ = self._make_bridge()
        # All steps succeed → plan COMPLETED
        plan = ExecutionPlan(
            goal="Completion test",
            steps=[
                PlanStep(id="s1", description="Step 1", priority=StepPriority.CRITICAL),
            ],
            max_total_tokens=5000,
        )
        run = WorkflowRun(
            run_id="r1", workflow_id="wf1", workflow_name="test",
            status=WorkflowStatus.SUCCESS,
            steps=[
                WorkflowStep(
                    id="s1", name="Step 1", type=StepType.TASK,
                    status=StepStatus.SUCCESS, output="ok",
                    started_at=1.0, finished_at=1.2,
                    config={"task_type": "nlp_task", "query": "Step 1", "predicted_tokens": 500},
                ),
            ],
            context={"difficulty": 5},
        )
        bridge.sync_results(plan, run)
        assert plan.status == PlanStatus.COMPLETED

    def test_sync_results_critical_failure(self):
        bridge, _ = self._make_bridge()
        plan = ExecutionPlan(
            goal="Critical fail test",
            steps=[
                PlanStep(id="s1", description="Critical", priority=StepPriority.CRITICAL),
            ],
            max_total_tokens=5000,
        )
        run = WorkflowRun(
            run_id="r1", workflow_id="wf1", workflow_name="test",
            status=WorkflowStatus.FAILED,
            steps=[
                WorkflowStep(
                    id="s1", name="Critical", type=StepType.TASK,
                    status=StepStatus.FAILED, error="crash",
                    started_at=1.0, finished_at=1.2,
                    config={"task_type": "nlp_task", "query": "Critical", "predicted_tokens": 500},
                ),
            ],
            context={"difficulty": 5},
        )
        bridge.sync_results(plan, run)
        assert plan.status == PlanStatus.FAILED


# =========================================================================
# PlanMonitor Tests
# =========================================================================


class TestPlanMonitor:

    def _make_plan(self, n_steps=3, max_tokens=3000):
        steps = []
        for i in range(n_steps):
            steps.append(PlanStep(
                id=f"s{i}", description=f"Step {i}",
                priority=StepPriority.NORMAL if i > 0 else StepPriority.CRITICAL,
                estimated_tokens=1000,
            ))
        return ExecutionPlan(goal="Monitor test", steps=steps, max_total_tokens=max_tokens)

    def test_observe_healthy_plan(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        # Complete step 0 within budget
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[0].actual_tokens = 500
        plan.tokens_used = 500
        actions = monitor.observe_step_completion(plan, plan.steps[0], confidence=0.9)
        assert actions == []  # No intervention needed

    def test_budget_overrun_triggers_reallocation(self):
        monitor = PlanMonitor()
        plan = self._make_plan(n_steps=5, max_tokens=5000)
        # First step uses too many tokens relative to progress
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[0].actual_tokens = 4500
        plan.tokens_used = 4500  # 20% progress, 4500 tokens → burn rate = 225
        actions = monitor.observe_step_completion(plan, plan.steps[0], confidence=0.9)
        assert AdaptiveAction.REALLOCATE_BUDGET in actions

    def test_failure_streak_triggers_skip(self):
        monitor = PlanMonitor()
        plan = self._make_plan(n_steps=5)
        # Mark 2 consecutive failures (non-critical)
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[1].status = PlanStatus.FAILED
        plan.steps[1].priority = StepPriority.NORMAL
        plan.steps[2].status = PlanStatus.FAILED
        plan.steps[2].priority = StepPriority.NORMAL
        actions = monitor.observe_step_completion(plan, plan.steps[2], confidence=0.8)
        assert AdaptiveAction.SKIP_LOW_PRIORITY in actions

    def test_critical_failure_streak_triggers_abort(self):
        monitor = PlanMonitor()
        plan = self._make_plan(n_steps=4)
        plan.steps[0].status = PlanStatus.FAILED
        plan.steps[0].priority = StepPriority.CRITICAL
        plan.steps[1].status = PlanStatus.FAILED
        plan.steps[1].priority = StepPriority.NORMAL
        actions = monitor.observe_step_completion(plan, plan.steps[1], confidence=0.8)
        assert AdaptiveAction.ABORT_PLAN in actions

    def test_confidence_drop_triggers_pause(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        plan.steps[0].status = PlanStatus.COMPLETED
        # Observe 3 low-confidence completions
        monitor.observe_step_completion(plan, plan.steps[0], confidence=0.2)
        monitor.observe_step_completion(plan, plan.steps[0], confidence=0.3)
        actions = monitor.observe_step_completion(plan, plan.steps[0], confidence=0.25)
        assert AdaptiveAction.PAUSE_PLAN in actions

    def test_projected_overrun_triggers_reduction(self):
        monitor = PlanMonitor()
        plan = self._make_plan(n_steps=5, max_tokens=1000)
        # 40% done, but already used 800 tokens → projected 2000, threshold 1300
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[1].status = PlanStatus.COMPLETED
        plan.tokens_used = 800
        actions = monitor.observe_step_completion(plan, plan.steps[1], confidence=0.9)
        assert AdaptiveAction.REDUCE_MAX_TOKENS in actions

    def test_apply_reallocate_budget(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        plan.steps[0].status = PlanStatus.COMPLETED
        # Steps 1 and 2 still DRAFT
        original_tokens = plan.steps[1].estimated_tokens
        monitor.apply_adaptive_actions(plan, [AdaptiveAction.REALLOCATE_BUDGET])
        assert plan.steps[1].estimated_tokens < original_tokens
        assert plan.steps[2].estimated_tokens < original_tokens

    def test_apply_skip_low_priority(self):
        monitor = PlanMonitor()
        plan = ExecutionPlan(
            goal="Skip test",
            steps=[
                PlanStep(id="s0", description="Keep", priority=StepPriority.HIGH),
                PlanStep(id="s1", description="Skip me", priority=StepPriority.LOW),
            ],
            max_total_tokens=5000,
        )
        monitor.apply_adaptive_actions(plan, [AdaptiveAction.SKIP_LOW_PRIORITY])
        assert plan.steps[0].status == PlanStatus.DRAFT  # HIGH not skipped
        assert plan.steps[1].status == PlanStatus.COMPLETED  # LOW skipped

    def test_apply_pause(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        monitor.apply_adaptive_actions(plan, [AdaptiveAction.PAUSE_PLAN])
        assert plan.status == PlanStatus.CHECKPOINT

    def test_apply_abort(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        monitor.apply_adaptive_actions(plan, [AdaptiveAction.ABORT_PLAN])
        assert plan.status == PlanStatus.FAILED

    def test_health_report_basic(self):
        monitor = PlanMonitor()
        plan = self._make_plan(max_tokens=5000)
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[0].actual_tokens = 500
        plan.tokens_used = 500
        monitor.observe_step_completion(plan, plan.steps[0], confidence=0.9)
        report = monitor.get_health_report(plan)
        assert isinstance(report, PlanHealthReport)
        assert report.plan_id == plan.id
        assert report.progress_pct > 0
        assert report.consecutive_failures == 0

    def test_health_report_confidence_trend_stable(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        plan.steps[0].status = PlanStatus.COMPLETED
        for _ in range(6):
            monitor.observe_step_completion(plan, plan.steps[0], confidence=0.85)
        report = monitor.get_health_report(plan)
        assert report.confidence_trend == "stable"

    def test_health_report_confidence_trend_degrading(self):
        monitor = PlanMonitor()
        plan = self._make_plan()
        plan.steps[0].status = PlanStatus.COMPLETED
        # Start high, end low
        for c in [0.95, 0.93, 0.90, 0.70, 0.65]:
            monitor.observe_step_completion(plan, plan.steps[0], confidence=c)
        report = monitor.get_health_report(plan)
        assert report.confidence_trend == "degrading"

    def test_get_events(self):
        monitor = PlanMonitor()
        plan = self._make_plan(n_steps=5, max_tokens=1000)
        plan.steps[0].status = PlanStatus.COMPLETED
        plan.steps[1].status = PlanStatus.COMPLETED
        plan.tokens_used = 800
        monitor.observe_step_completion(plan, plan.steps[1], confidence=0.9)
        events = monitor.get_events(plan_id=plan.id)
        assert len(events) > 0
        assert all(e["plan_id"] == plan.id for e in events)

    def test_event_filter_by_plan_id(self):
        monitor = PlanMonitor()
        plan1 = self._make_plan()
        plan1.steps[0].status = PlanStatus.COMPLETED
        plan2 = self._make_plan()
        plan2.steps[0].status = PlanStatus.COMPLETED
        plan2.tokens_used = 50000
        monitor.observe_step_completion(plan2, plan2.steps[0], confidence=0.9)
        events_plan1 = monitor.get_events(plan_id=plan1.id)
        assert len(events_plan1) == 0


# =========================================================================
# End-to-End Integration Test
# =========================================================================


class TestEndToEndPlanWorkflow:

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Plan creation → workflow conversion → execution → sync → monitoring."""
        coordinator = PlanCoordinator()
        engine = WorkflowEngine()
        predictor = TokenPredictor()
        bridge = PlanWorkflowBridge(engine, predictor)
        monitor = PlanMonitor()

        # 1. Create and validate plan
        plan = coordinator.create_plan(
            goal="Build login system",
            subtasks=["Design schema", "Implement API", "Write tests"],
            difficulty=7,
            max_tokens=10000,
        )
        plan.context["difficulty"] = 7
        issues = coordinator.validate_plan(plan)
        assert issues == []
        assert plan.status == PlanStatus.VALIDATED

        # 2. Convert to workflow
        wf = bridge.plan_to_workflow(plan, task_type="code_generation")
        assert len(wf.steps) == 3
        assert all(s.config.get("token_budget", 0) > 0 for s in wf.steps)

        # 3. Register and start
        async def mock_executor(step, ctx):
            await asyncio.sleep(0.01)
            return {"tokens_used": 500, "result": f"done_{step.id}"}

        engine.register_executor(StepType.TASK, mock_executor)
        engine.register_workflow(wf)
        run = await engine.start_workflow(wf.id, triggered_by="test")

        # Wait for execution to finish
        for _ in range(50):
            await asyncio.sleep(0.1)
            r = engine.get_run(run.run_id)
            if r and r.status in (WorkflowStatus.SUCCESS, WorkflowStatus.FAILED):
                break

        run = engine.get_run(run.run_id)
        assert run.status == WorkflowStatus.SUCCESS

        # 4. Sync results back
        bridge.sync_results(plan, run)
        assert plan.status == PlanStatus.COMPLETED
        assert plan.tokens_used > 0

        # 5. Monitor health
        report = monitor.get_health_report(plan)
        assert report.progress_pct == 100.0
        assert report.consecutive_failures == 0

        # 6. Verify predictor learned
        stats = predictor.get_accuracy_stats()
        assert stats["observations"] == 3
