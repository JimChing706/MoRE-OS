"""Tests for Workflow Engine, Deployment Manager, and Session Manager."""

import asyncio
import pytest

from more_core.workflows.engine import (
    WorkflowEngine, WorkflowDefinition, WorkflowStep,
    WorkflowRun, WorkflowStatus, StepStatus, StepType,
)
from more_core.deploy.manager import (
    DeploymentManager, DeploymentStatus, DeploymentType,
)
from more_core.runtime.sessions import SessionManager


# -- Workflow Engine -------------------------------------------------------

def test_workflow_registration():
    engine = WorkflowEngine()
    defn = WorkflowDefinition(
        id="wf1", name="Test Workflow",
        steps=[WorkflowStep(id="s1", name="step1", type=StepType.TASK)],
    )
    engine.register_workflow(defn)
    assert len(engine.list_workflows()) == 1
    assert engine.get_workflow("wf1") is not None


def test_workflow_unregister():
    engine = WorkflowEngine()
    defn = WorkflowDefinition(id="wf1", name="Test")
    engine.register_workflow(defn)
    engine.unregister_workflow("wf1")
    assert engine.get_workflow("wf1") is None


@pytest.mark.asyncio
async def test_workflow_run_simple():
    engine = WorkflowEngine()
    # Register a simple executor for TASK type
    async def task_executor(step, ctx):
        return f"done_{step.id}"
    engine.register_executor(StepType.TASK, task_executor)

    defn = WorkflowDefinition(
        id="wf_test", name="Simple",
        steps=[
            WorkflowStep(id="s1", name="step1", type=StepType.TASK),
            WorkflowStep(id="s2", name="step2", type=StepType.TASK, depends_on=["s1"]),
        ],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_test")
    # Wait for completion
    await asyncio.sleep(0.3)
    assert run.status == WorkflowStatus.SUCCESS
    assert all(s.status == StepStatus.SUCCESS for s in run.steps)


@pytest.mark.asyncio
async def test_workflow_run_parallel_steps():
    engine = WorkflowEngine()
    results = []

    async def task_executor(step, ctx):
        results.append(step.id)
        return step.id
    engine.register_executor(StepType.TASK, task_executor)

    defn = WorkflowDefinition(
        id="wf_par", name="Parallel",
        steps=[
            WorkflowStep(id="a", name="A", type=StepType.TASK),
            WorkflowStep(id="b", name="B", type=StepType.TASK),
            WorkflowStep(id="c", name="C", type=StepType.TASK, depends_on=["a", "b"]),
        ],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_par")
    await asyncio.sleep(0.3)
    assert run.status == WorkflowStatus.SUCCESS
    # C should only run after A and B
    assert results.index("c") > results.index("a")
    assert results.index("c") > results.index("b")


@pytest.mark.asyncio
async def test_workflow_run_with_failure():
    engine = WorkflowEngine()

    async def fail_executor(step, ctx):
        raise RuntimeError("intentional failure")
    engine.register_executor(StepType.TASK, fail_executor)

    defn = WorkflowDefinition(
        id="wf_fail", name="Failing",
        steps=[WorkflowStep(id="s1", name="failing_step", type=StepType.TASK)],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_fail")
    await asyncio.sleep(0.3)
    assert run.status == WorkflowStatus.FAILED


@pytest.mark.asyncio
async def test_workflow_delay_step():
    engine = WorkflowEngine()
    defn = WorkflowDefinition(
        id="wf_delay", name="Delay Test",
        steps=[WorkflowStep(id="d1", name="wait", type=StepType.DELAY, config={"seconds": 0.1})],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_delay")
    await asyncio.sleep(0.5)
    assert run.status == WorkflowStatus.SUCCESS


@pytest.mark.asyncio
async def test_workflow_cancel():
    engine = WorkflowEngine()

    async def slow_executor(step, ctx):
        await asyncio.sleep(10)
    engine.register_executor(StepType.TASK, slow_executor)

    defn = WorkflowDefinition(
        id="wf_cancel", name="Cancellable",
        steps=[WorkflowStep(id="s1", name="slow", type=StepType.TASK)],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_cancel")
    await asyncio.sleep(0.1)
    ok = await engine.cancel_run(run.run_id)
    assert ok
    await asyncio.sleep(0.2)
    assert run.status == WorkflowStatus.CANCELLED


@pytest.mark.asyncio
async def test_workflow_conditional_skip():
    engine = WorkflowEngine()

    async def task_executor(step, ctx):
        return "ok"
    engine.register_executor(StepType.TASK, task_executor)

    defn = WorkflowDefinition(
        id="wf_cond", name="Conditional",
        steps=[
            WorkflowStep(id="s1", name="always", type=StepType.TASK),
            WorkflowStep(id="s2", name="skipped", type=StepType.TASK, condition="ctx.get('run_s2', False)"),
        ],
    )
    engine.register_workflow(defn)
    run = await engine.start_workflow("wf_cond", context={"run_s2": False})
    await asyncio.sleep(0.3)
    s2 = next(s for s in run.steps if s.id == "s2")
    assert s2.status == StepStatus.SKIPPED


def test_workflow_stats():
    engine = WorkflowEngine()
    engine.register_workflow(WorkflowDefinition(id="a", name="A"))
    engine.register_workflow(WorkflowDefinition(id="b", name="B"))
    stats = engine.stats()
    assert stats["total_workflows"] == 2


def test_workflow_run_summary():
    run = WorkflowRun(
        run_id="r1", workflow_id="w1", workflow_name="Test",
        steps=[
            WorkflowStep(id="s1", name="a", type=StepType.TASK, status=StepStatus.SUCCESS),
            WorkflowStep(id="s2", name="b", type=StepType.TASK, status=StepStatus.RUNNING),
        ],
    )
    summary = run.to_summary()
    assert summary["progress"]["done"] == 1
    assert summary["progress"]["running"] == 1


# -- Deployment Manager ----------------------------------------------------

@pytest.mark.asyncio
async def test_deploy_and_list():
    mgr = DeploymentManager()
    dep = await mgr.deploy("test-hand", DeploymentType.HAND, "researcher")
    assert dep.status == DeploymentStatus.RUNNING
    assert len(mgr.list_deployments()) == 1


@pytest.mark.asyncio
async def test_deploy_undeploy():
    mgr = DeploymentManager()
    dep = await mgr.deploy("x", DeploymentType.SKILL, "skill1")
    ok = await mgr.undeploy(dep.id)
    assert ok
    assert dep.status == DeploymentStatus.STOPPED


@pytest.mark.asyncio
async def test_deploy_restart():
    mgr = DeploymentManager()
    dep = await mgr.deploy("y", DeploymentType.HAND, "coder")
    ok = await mgr.restart(dep.id)
    assert ok
    assert dep.restart_count == 1
    assert dep.status == DeploymentStatus.RUNNING


@pytest.mark.asyncio
async def test_deploy_remove():
    mgr = DeploymentManager()
    dep = await mgr.deploy("z", DeploymentType.WORKFLOW, "wf1")
    ok = await mgr.remove(dep.id)
    assert ok
    assert len(mgr.list_deployments()) == 0


def test_deployment_stats():
    mgr = DeploymentManager()
    stats = mgr.stats()
    assert stats["total"] == 0


@pytest.mark.asyncio
async def test_deploy_health_marking():
    mgr = DeploymentManager()
    dep = await mgr.deploy("h", DeploymentType.HAND, "monitor")
    mgr.mark_unhealthy(dep.id, "connection lost")
    assert not dep.health.healthy
    assert dep.health.message == "connection lost"
    mgr.mark_healthy(dep.id)
    assert dep.health.healthy


@pytest.mark.asyncio
async def test_deploy_filter_by_type():
    mgr = DeploymentManager()
    await mgr.deploy("h1", DeploymentType.HAND, "a")
    await mgr.deploy("s1", DeploymentType.SKILL, "b")
    hands = mgr.list_deployments(dtype=DeploymentType.HAND)
    assert len(hands) == 1
    assert hands[0]["type"] == "hand"


# -- Session Manager -------------------------------------------------------

def test_session_create():
    mgr = SessionManager()
    session = mgr.create_session("user1", user_name="Alice", role="operator")
    assert session.user_id == "user1"
    assert session.role == "operator"


def test_session_get_and_touch():
    mgr = SessionManager()
    session = mgr.create_session("u1")
    retrieved = mgr.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.user_id == "u1"


def test_session_destroy():
    mgr = SessionManager()
    s = mgr.create_session("u1")
    mgr.destroy_session(s.session_id)
    assert mgr.get_session(s.session_id) is None


def test_session_subscribe():
    mgr = SessionManager()
    s = mgr.create_session("u1")
    mgr.subscribe(s.session_id, "hands")
    mgr.subscribe(s.session_id, "workflows")
    assert "hands" in s.subscriptions
    assert "workflows" in s.subscriptions


def test_session_unsubscribe():
    mgr = SessionManager()
    s = mgr.create_session("u1")
    mgr.subscribe(s.session_id, "hands")
    mgr.unsubscribe(s.session_id, "hands")
    assert "hands" not in s.subscriptions


def test_session_list():
    mgr = SessionManager()
    mgr.create_session("u1")
    mgr.create_session("u2")
    sessions = mgr.list_sessions()
    assert len(sessions) == 2


def test_session_stats():
    mgr = SessionManager()
    mgr.create_session("u1", role="admin")
    mgr.create_session("u2", role="viewer")
    stats = mgr.stats()
    assert stats["active_sessions"] == 2
    assert stats["by_role"]["admin"] == 1


def test_session_expired():
    mgr = SessionManager(session_timeout_s=0.01)
    s = mgr.create_session("u1")
    import time
    time.sleep(0.02)
    assert mgr.get_session(s.session_id) is None


def test_session_cleanup():
    mgr = SessionManager(session_timeout_s=0.01)
    mgr.create_session("u1")
    mgr.create_session("u2")
    import time
    time.sleep(0.02)
    removed = mgr.cleanup_expired()
    assert removed == 2
