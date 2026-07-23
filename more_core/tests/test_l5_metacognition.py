"""Tests for L5 — Metacognition Layer (calibration, plan monitoring, self-modification)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.core.errors import MoREError
from more_core.core.types import LayerId, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l5_metacognition import MetacognitionLayer
from more_core.planning.coordinator import PlanStatus


def _make_ctx(
    task_type: TaskType = TaskType.NLP_TASK,
    query: str = "test query",
    actor: str = "alice",
    decomposed: bool = False,
    plan_id: str | None = None,
    enable_metacognition: bool = True,
    allow_self_improvement: bool = False,
) -> LayerContext:
    core = MagicMock()
    core.settings.enable_metacognition = enable_metacognition

    # Metacognition engine
    core.metacognition = MagicMock()
    core.metacognition.calibrate = AsyncMock(
        return_value={"alignment": 0.95, "num_samples": 10}
    )
    core.metacognition.maybe_self_modify = AsyncMock(
        return_value={"modified": False}
    )

    # Plan monitor
    core.plan_monitor = MagicMock()
    core.plan_monitor.observe_step_completion.return_value = []
    core.plan_monitor.apply_adaptive_actions.return_value = {}
    health_report = MagicMock()
    health_report.status = "on_track"
    health_report.plan_id = "plan-123"
    health_report.progress_pct = 50.0
    health_report.budget_burn_rate = 0.5
    health_report.budget_will_exceed = False
    health_report.confidence_trend = "stable"
    core.plan_monitor.get_health_report.return_value = health_report

    # Planner
    core.planner = MagicMock()
    if plan_id:
        plan = MagicMock()
        plan.id = plan_id
        step = MagicMock()
        step.status = PlanStatus.COMPLETED
        plan.steps = [step]
        core.planner.get_plan.return_value = plan
    else:
        core.planner.get_plan.return_value = None

    req = MagicMock()
    req.type = task_type
    req.query = query
    req.context = {"actor": actor}
    req.id = "test-l5-task"
    req.allow_self_improvement = allow_self_improvement

    ctx = LayerContext(core=core, request=req)
    ctx.scratch = {}
    if decomposed:
        ctx.scratch["plan"] = {
            "subtasks": ["s1", "s2"],
            "decomposed": True,
            "plan_id": plan_id,
        }
    return ctx


class TestActorBlocking:

    @pytest.mark.asyncio
    async def test_blocked_actor_returns_access_denied(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mgr = MagicMock()
            mgr.is_actor_blocked.return_value = True
            mgr.handle_unauthorized_access = AsyncMock()
            mock_get_incident.return_value = mgr

            ctx = _make_ctx(actor="blocked_user")
            result = await MetacognitionLayer().process(ctx)
            assert result.output["blocked"] is True
            assert result.confidence == 0.0
            assert "ACCESS DENIED" in result.description
            mgr.handle_unauthorized_access.assert_called_once()

    @pytest.mark.asyncio
    async def test_unblocked_actor_proceeds_normally(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mgr = MagicMock()
            mgr.is_actor_blocked.return_value = False
            mock_get_incident.return_value = mgr

            ctx = _make_ctx(actor="trusted_user")
            result = await MetacognitionLayer().process(ctx)
            assert result.output.get("blocked") is None or not result.output.get("blocked")


class TestCalibration:

    @pytest.mark.asyncio
    async def test_calibration_runs_and_stores_in_scratch(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx()
            await MetacognitionLayer().process(ctx)
            assert "calibration" in ctx.scratch
            assert ctx.scratch["calibration"]["alignment"] == 0.95

    @pytest.mark.asyncio
    async def test_confidence_from_calibration_alignment(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx()
            result = await MetacognitionLayer().process(ctx)
            assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_description_contains_alignment(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx()
            result = await MetacognitionLayer().process(ctx)
            assert "aligned=0.95" in result.description


class TestPlanMonitoring:

    @pytest.mark.asyncio
    async def test_no_plan_returns_no_active_plan(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(decomposed=False)
            await MetacognitionLayer().process(ctx)
            assert ctx.scratch.get("plan_health") is None

    @pytest.mark.asyncio
    async def test_decomposed_plan_triggers_monitoring(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(
                decomposed=True,
                plan_id="plan-123",
            )
            await MetacognitionLayer().process(ctx)
            assert ctx.scratch["plan_health"]["status"] == "on_track"

    @pytest.mark.asyncio
    async def test_plan_without_plan_id_reports_pending(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(decomposed=True, plan_id=None)
            ctx.scratch["plan"] = {"subtasks": ["s1"], "decomposed": True}
            await MetacognitionLayer().process(ctx)
            assert ctx.scratch["plan_health"]["status"] in ("no_active_plan",)

    @pytest.mark.asyncio
    async def test_plan_health_in_output(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(decomposed=True, plan_id="plan-123")
            result = await MetacognitionLayer().process(ctx)
            assert result.output["plan_health"] is not None
            assert result.output["plan_health"]["status"] == "on_track"


class TestSelfModification:

    @pytest.mark.asyncio
    async def test_self_modification_when_enabled(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(
                enable_metacognition=True,
                allow_self_improvement=True,
            )
            ctx.core.metacognition.maybe_self_modify = AsyncMock(
                return_value={
                    "modified": True,
                    "changes": ["adjusted budget"],
                }
            )
            await MetacognitionLayer().process(ctx)
            ctx.core.metacognition.maybe_self_modify.assert_called_once()

    @pytest.mark.asyncio
    async def test_self_modification_disabled_no_call(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(
                enable_metacognition=False,
                allow_self_improvement=False,
            )
            await MetacognitionLayer().process(ctx)
            ctx.core.metacognition.maybe_self_modify.assert_not_called()

    @pytest.mark.asyncio
    async def test_self_modification_gated_by_settings_and_request(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            # Setting enabled but request disallows
            ctx = _make_ctx(
                enable_metacognition=True,
                allow_self_improvement=False,
            )
            await MetacognitionLayer().process(ctx)
            ctx.core.metacognition.maybe_self_modify.assert_not_called()


class TestCodeTaskAbortSuppression:

    @pytest.mark.asyncio
    async def test_non_code_task_abort_raises(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(
                task_type=TaskType.NLP_TASK,
                decomposed=True,
                plan_id="plan-123",
            )
            abort_action = MagicMock()
            abort_action.value = "abort"
            ctx.core.plan_monitor.observe_step_completion.return_value = [abort_action]
            ctx.core.plan_monitor.apply_adaptive_actions.return_value = {
                "aborted": True
            }
            health_report = MagicMock()
            health_report.status = "budget_exceeded"
            health_report.plan_id = "plan-123"
            health_report.progress_pct = 30.0
            health_report.budget_burn_rate = 1.5
            health_report.budget_will_exceed = True
            health_report.confidence_trend = "declining"
            ctx.core.plan_monitor.get_health_report.return_value = health_report

            with pytest.raises(MoREError, match="Plan aborted"):
                await MetacognitionLayer().process(ctx)

    @pytest.mark.asyncio
    async def test_code_task_abort_suppressed(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(
                task_type=TaskType.CODE_GENERATION,
                decomposed=True,
                plan_id="plan-123",
            )
            ctx.core.plan_monitor.observe_step_completion.return_value = []
            ctx.core.plan_monitor.apply_adaptive_actions.return_value = {
                "aborted": True
            }
            health_report = MagicMock()
            health_report.status = "budget_exceeded"
            health_report.plan_id = "plan-123"
            health_report.progress_pct = 30.0
            health_report.budget_burn_rate = 1.5
            health_report.budget_will_exceed = True
            health_report.confidence_trend = "declining"
            ctx.core.plan_monitor.get_health_report.return_value = health_report

            # Should NOT raise, just log a warning
            result = await MetacognitionLayer().process(ctx)
            assert result.layer == LayerId.L5


class TestPlanHealthReport:

    @pytest.mark.asyncio
    async def test_layer_id(self):
        assert MetacognitionLayer().layer_id == LayerId.L5

    @pytest.mark.asyncio
    async def test_output_contains_calibration_and_structured_plan(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx()
            ctx.scratch["structured_plan"] = {"phases": [{"name": "phase1"}]}
            result = await MetacognitionLayer().process(ctx)
            assert "calibration" in result.output
            assert result.output["structured_plan"] is not None

    @pytest.mark.asyncio
    async def test_description_with_plan_health(self):
        with patch(
            "more_core.layers.l5_metacognition.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()
            mock_get_incident.return_value.is_actor_blocked.return_value = False

            ctx = _make_ctx(decomposed=True, plan_id="plan-123")
            result = await MetacognitionLayer().process(ctx)
            assert "plan_health=on_track" in result.description
