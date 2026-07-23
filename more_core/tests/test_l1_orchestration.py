"""Tests for L1 — Orchestration Layer (execution strategy, resource budget)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from more_core.core.types import LayerId, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l1_orchestration import (
    ExecutionStrategy,
    ModelHint,
    OrchestrationLayer,
)


def _make_ctx(
    task_type: TaskType = TaskType.NLP_TASK,
    difficulty: int = 5,
    capability: int = 7,
    has_subtasks: bool = False,
) -> LayerContext:
    core = MagicMock()
    core.settings = MagicMock()
    req = MagicMock()
    req.type = task_type
    req.query = "test"
    req.context = {}
    ctx = LayerContext(core=core, request=req)
    ctx.scratch["difficulty"] = difficulty
    ctx.scratch["capability"] = capability
    if has_subtasks:
        ctx.scratch["plan"] = {
            "subtasks": ["step 1", "step 2", "step 3"],
        }
    return ctx


class TestOrchestrationLayer:

    @pytest.mark.asyncio
    async def test_mode_autonomous_when_capability_exceeds_difficulty(self):
        ctx = _make_ctx(difficulty=3, capability=7)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["mode"] == "autonomous"

    @pytest.mark.asyncio
    async def test_mode_collaborative_when_gap_large(self):
        ctx = _make_ctx(difficulty=9, capability=4)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["mode"] == "collaborative"

    @pytest.mark.asyncio
    async def test_mode_standard_when_balanced(self):
        ctx = _make_ctx(difficulty=5, capability=5)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["mode"] == "standard"

    @pytest.mark.asyncio
    async def test_strategy_precise_for_reasoning_tasks(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, difficulty=6)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["strategy"] == ExecutionStrategy.PRECISE.value

    @pytest.mark.asyncio
    async def test_strategy_precise_for_collaborative_mode(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, difficulty=9, capability=4)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["strategy"] == ExecutionStrategy.PRECISE.value

    @pytest.mark.asyncio
    async def test_strategy_creative_for_low_difficulty(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, difficulty=2)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["strategy"] == ExecutionStrategy.CREATIVE.value

    @pytest.mark.asyncio
    async def test_strategy_balanced_for_code_above_threshold(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, difficulty=6)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["strategy"] == ExecutionStrategy.BALANCED.value

    @pytest.mark.asyncio
    async def test_model_reasoning_for_hard_math(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, difficulty=7)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["model_hint"] == ModelHint.REASONING.value

    @pytest.mark.asyncio
    async def test_model_standard_for_easy_reasoning(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, difficulty=3)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["model_hint"] == ModelHint.STANDARD.value

    @pytest.mark.asyncio
    async def test_model_standard_for_nlp(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, difficulty=8)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["model_hint"] == ModelHint.STANDARD.value

    @pytest.mark.asyncio
    async def test_code_task_receives_minimum_code_tokens(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, difficulty=4)
        await OrchestrationLayer().process(ctx)
        tokens = ctx.request.context["max_tokens"]
        assert tokens >= 4096

    @pytest.mark.asyncio
    async def test_high_difficulty_code_gets_max_budget(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, difficulty=9)
        await OrchestrationLayer().process(ctx)
        tokens = ctx.request.context["max_tokens"]
        assert tokens >= 8192

    @pytest.mark.asyncio
    async def test_collaborative_mode_gets_high_budget(self):
        ctx = _make_ctx(task_type=TaskType.DATA_ANALYSIS, difficulty=9, capability=4)
        await OrchestrationLayer().process(ctx)
        tokens = ctx.request.context["max_tokens"]
        assert tokens >= 4096

    @pytest.mark.asyncio
    async def test_easy_nlp_low_token_budget(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, difficulty=2)
        await OrchestrationLayer().process(ctx)
        tokens = ctx.request.context["max_tokens"]
        assert tokens < 4096

    @pytest.mark.asyncio
    async def test_precise_strategy_low_temperature(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, difficulty=7)
        await OrchestrationLayer().process(ctx)
        assert ctx.request.context["temperature"] <= 0.4

    @pytest.mark.asyncio
    async def test_creative_strategy_higher_temperature(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, difficulty=2)
        await OrchestrationLayer().process(ctx)
        assert ctx.request.context["temperature"] >= 0.7

    @pytest.mark.asyncio
    async def test_context_has_all_expected_keys(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, difficulty=6)
        await OrchestrationLayer().process(ctx)
        for key in ("temperature", "max_tokens", "execution_strategy", "model_hint"):
            assert key in ctx.request.context, f"missing context key: {key}"

    @pytest.mark.asyncio
    async def test_scratch_has_orchestration_plan(self):
        ctx = _make_ctx()
        await OrchestrationLayer().process(ctx)
        assert "orchestration_plan" in ctx.scratch
        plan = ctx.scratch["orchestration_plan"]
        assert "mode" in plan
        assert "strategy" in plan
        assert "model_hint" in plan

    @pytest.mark.asyncio
    async def test_subtask_flag_set_when_decomposed(self):
        ctx = _make_ctx(has_subtasks=True)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["has_subtasks"] is True
        assert ctx.scratch.get("subtask_count") == 3

    @pytest.mark.asyncio
    async def test_no_subtask_flag_when_not_decomposed(self):
        ctx = _make_ctx(has_subtasks=False)
        result = await OrchestrationLayer().process(ctx)
        assert result.output["has_subtasks"] is False

    def test_layer_id_is_l1(self):
        assert OrchestrationLayer().layer_id == LayerId.L1

    @pytest.mark.asyncio
    async def test_result_has_expected_fields(self):
        ctx = _make_ctx()
        result = await OrchestrationLayer().process(ctx)
        assert result.layer == LayerId.L1
        assert result.description
        assert result.confidence == 0.9
        assert isinstance(result.output, dict)
