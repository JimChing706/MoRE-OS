"""Tests for PlanCoordinator — rigorous task planning with dependency tracking."""

import pytest

from more_core.planning.coordinator import (
    PlanCoordinator,
    ExecutionPlan,
    PlanStep,
    PlanStatus,
    StepPriority,
)


@pytest.fixture
def coordinator():
    return PlanCoordinator()


def test_create_plan_basic(coordinator):
    plan = coordinator.create_plan(
        goal="Build auth module",
        subtasks=["Design API", "Implement endpoints", "Write tests"],
    )
    assert plan.status == PlanStatus.DRAFT
    assert len(plan.steps) == 3
    assert plan.steps[0].priority == StepPriority.CRITICAL
    assert plan.steps[1].depends_on == ["step_000"]
    assert plan.steps[2].depends_on == ["step_001"]


def test_validate_plan_success(coordinator):
    plan = coordinator.create_plan(
        goal="Simple task",
        subtasks=["Step A", "Step B"],
    )
    issues = coordinator.validate_plan(plan)
    assert issues == []
    assert plan.status == PlanStatus.VALIDATED


def test_validate_plan_empty_steps(coordinator):
    plan = ExecutionPlan(goal="Empty")
    issues = coordinator.validate_plan(plan)
    assert "Plan has no steps" in issues


def test_validate_plan_detects_missing_dep(coordinator):
    plan = ExecutionPlan(
        goal="Bad deps",
        steps=[
            PlanStep(id="s1", description="A", depends_on=["nonexistent"]),
        ],
    )
    issues = coordinator.validate_plan(plan)
    assert any("unknown step" in i for i in issues)


def test_validate_plan_detects_cycle(coordinator):
    plan = ExecutionPlan(
        goal="Cycle",
        steps=[
            PlanStep(id="a", description="A", depends_on=["b"]),
            PlanStep(id="b", description="B", depends_on=["a"]),
        ],
    )
    issues = coordinator.validate_plan(plan)
    assert any("cycle" in i.lower() for i in issues)


def test_execution_order_sequential(coordinator):
    plan = coordinator.create_plan(
        goal="Sequential",
        subtasks=["First", "Second", "Third"],
    )
    waves = coordinator.get_execution_order(plan)
    assert len(waves) == 3  # Linear dependency → 3 waves of 1
    assert len(waves[0]) == 1
    assert waves[0][0].description == "First"


def test_execution_order_parallel():
    """Steps with no deps can run in parallel."""
    coord = PlanCoordinator()
    plan = ExecutionPlan(
        goal="Parallel",
        steps=[
            PlanStep(id="a", description="A"),
            PlanStep(id="b", description="B"),
            PlanStep(id="c", description="C", depends_on=["a", "b"]),
        ],
    )
    waves = coord.get_execution_order(plan)
    assert len(waves) == 2  # [a, b] then [c]
    assert len(waves[0]) == 2
    assert len(waves[1]) == 1


def test_record_step_result_updates_budget(coordinator):
    plan = coordinator.create_plan(
        goal="Budget test",
        subtasks=["Step 1", "Step 2"],
        max_tokens=5000,
    )
    coordinator.record_step_result(
        plan, "step_000", output="done", tokens_used=2000, duration_ms=100.0
    )
    assert plan.tokens_used == 2000
    assert plan.steps[0].status == PlanStatus.COMPLETED
    assert plan.steps[0].actual_tokens == 2000


def test_over_budget_detection(coordinator):
    plan = coordinator.create_plan(
        goal="Over budget",
        subtasks=["Heavy step"],
        max_tokens=100,
    )
    coordinator.record_step_result(plan, "step_000", output="x", tokens_used=200, duration_ms=50.0)
    assert plan.is_over_budget


def test_checkpoint_and_progress(coordinator):
    plan = coordinator.create_plan(
        goal="Checkpoint test",
        subtasks=["A", "B", "C"],
    )
    coordinator.record_step_result(plan, "step_000", output="done", tokens_used=100, success=True)
    coordinator.checkpoint(plan)

    assert len(plan.checkpoints) == 1
    assert plan.checkpoints[0]["progress_pct"] == pytest.approx(33.3, abs=0.5)
    assert plan.progress_pct == pytest.approx(33.3, abs=0.5)


def test_plan_summary(coordinator):
    plan = coordinator.create_plan(goal="Summary test", subtasks=["X"])
    summary = plan.to_summary()
    assert summary["goal"] == "Summary test"
    assert summary["steps"] == 1
    assert summary["status"] == "draft"


def test_list_and_stats(coordinator):
    coordinator.create_plan(goal="A", subtasks=["1"])
    coordinator.create_plan(goal="B", subtasks=["1", "2"])
    plans = coordinator.list_plans()
    assert len(plans) == 2
    stats = coordinator.stats()
    assert stats["total_plans"] == 2
