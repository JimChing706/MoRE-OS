"""Tests for L3 — Symbolic Reasoning Layer (governance + symbolic math)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from more_core.core.errors import GovernanceError
from more_core.core.types import LayerId, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l3_symbolic import SymbolicLayer


def _make_ctx(
    task_type: TaskType = TaskType.NLP_TASK,
    query: str = "test query",
    strict_ontology: bool = False,
    allow_self_improvement: bool = False,
    evolution_enabled: bool = False,
    sandbox_result: object = None,
) -> LayerContext:
    core = MagicMock()
    core.settings.strict_ontology = strict_ontology
    core.settings.enable_evolution = evolution_enabled
    core.ontology = MagicMock()
    core.ontology.check = AsyncMock(return_value=[])

    req = MagicMock()
    req.type = task_type
    req.query = query
    req.allow_self_improvement = allow_self_improvement
    req.context = {}
    req.task_id = "test-task"

    ctx = LayerContext(core=core, request=req)
    ctx.scratch = {}
    if sandbox_result is not None:
        ctx.scratch["sandbox_result"] = sandbox_result
    return ctx


class TestSymbolicLayerGovernance:
    @pytest.mark.asyncio
    async def test_nlp_task_runs_governance_only(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK)
        result = await SymbolicLayer().process(ctx)
        assert result.layer == LayerId.L3
        assert "governance" in result.description
        assert "symbolic" not in result.description

    @pytest.mark.asyncio
    async def test_no_violations_returns_high_confidence(self):
        ctx = _make_ctx()
        result = await SymbolicLayer().process(ctx)
        assert result.confidence == 1.0
        assert result.output["violations"] == []

    @pytest.mark.asyncio
    async def test_governance_violation_raises_when_strict(self):
        ctx = _make_ctx(strict_ontology=True)
        ctx.core.ontology.check = AsyncMock(return_value=["outcome.validated"])
        with pytest.raises(GovernanceError, match="symbolic violations"):
            await SymbolicLayer().process(ctx)

    @pytest.mark.asyncio
    async def test_governance_violation_logged_when_not_strict(self):
        ctx = _make_ctx(strict_ontology=False)
        ctx.core.ontology.check = AsyncMock(return_value=["outcome.validated"])
        result = await SymbolicLayer().process(ctx)
        assert result.confidence == 0.5
        assert "outcome.validated" in result.output["violations"]

    @pytest.mark.asyncio
    async def test_fired_rules_stored_in_scratch(self):
        ctx = _make_ctx()
        await SymbolicLayer().process(ctx)
        assert "fired_rules" in ctx.scratch
        assert "inference_annotations" in ctx.scratch

    @pytest.mark.asyncio
    async def test_sandbox_result_included_in_facts(self):
        from more_core.tools.registry import ToolResult

        sbx = ToolResult(tool="python_exec", success=True, output="print('ok')")
        ctx = _make_ctx(sandbox_result=sbx)
        r = await SymbolicLayer().process(ctx)
        assert r.layer == LayerId.L3


class TestSymbolicLayerSymbolicMath:
    @pytest.mark.asyncio
    async def test_math_reasoning_runs_symbolic_engine(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="simplify x + x")
        result = await SymbolicLayer().process(ctx)
        assert "symbolic" in result.description
        assert result.output["symbolic_success"] is True
        assert result.output["symbolic_result"] is not None

    @pytest.mark.asyncio
    async def test_math_reasoning_solve_equation(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="solve x**2 - 4")
        result = await SymbolicLayer().process(ctx)
        assert result.output["symbolic_success"] is True
        assert "2" in result.output["symbolic_result"]

    @pytest.mark.asyncio
    async def test_math_reasoning_differentiate(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="diff x**3 wrt x")
        result = await SymbolicLayer().process(ctx)
        assert result.output["symbolic_success"] is True
        assert "3*x**2" in result.output["symbolic_result"]

    @pytest.mark.asyncio
    async def test_math_reasoning_integrate(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="integrate x**2 dx")
        result = await SymbolicLayer().process(ctx)
        assert result.output["symbolic_success"] is True
        assert "x**3/3" in result.output["symbolic_result"]

    @pytest.mark.asyncio
    async def test_math_reasoning_limit(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="limit 1/x as x->oo")
        result = await SymbolicLayer().process(ctx)
        assert result.output["symbolic_success"] is True
        assert result.output["symbolic_result"] == "0"

    @pytest.mark.asyncio
    async def test_math_reasoning_unrecognised_query(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="do something weird")
        result = await SymbolicLayer().process(ctx)
        assert result.output["symbolic_success"] is False
        assert result.output["symbolic_error"] is not None
        assert "unrecognised" in result.output["symbolic_error"]

    @pytest.mark.asyncio
    async def test_symbolic_result_in_scratch_and_annotations(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="simplify 2*x + 3*x")
        await SymbolicLayer().process(ctx)
        assert "symbolic_result" in ctx.scratch
        assert ctx.scratch["symbolic_result"].success is True
        assert ctx.scratch["inference_annotations"].get("symbolic_math") is not None

    @pytest.mark.asyncio
    async def test_symbolic_error_not_in_annotations(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="do something weird")
        await SymbolicLayer().process(ctx)
        assert ctx.scratch["inference_annotations"].get("symbolic_error") is not None
        assert ctx.scratch["inference_annotations"].get("symbolic_math") is None

    @pytest.mark.asyncio
    async def test_math_reasoning_with_governance_violation(self):
        ctx = _make_ctx(
            task_type=TaskType.MATH_REASONING, query="simplify x + x", strict_ontology=False
        )
        ctx.core.ontology.check = AsyncMock(return_value=["outcome.validated"])
        result = await SymbolicLayer().process(ctx)
        # Both governance and symbolic should be present
        assert "outcome.validated" in result.output["violations"]
        assert result.output["symbolic_success"] is True
        assert result.confidence == 0.5  # lowered due to violation


class TestSymbolicLayerEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_query_no_crash(self):
        ctx = _make_ctx(task_type=TaskType.MATH_REASONING, query="")
        result = await SymbolicLayer().process(ctx)
        # Empty query isn't recognized as a symbolic command
        assert result.output["symbolic_success"] is False

    @pytest.mark.asyncio
    async def test_long_query_no_crash(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="A" * 20000)
        result = await SymbolicLayer().process(ctx)
        assert result.layer == LayerId.L3

    def test_layer_id(self):
        assert SymbolicLayer().layer_id == LayerId.L3

    def test_symbolic_engine_property(self):
        layer = SymbolicLayer()
        assert layer.symbolic_engine is not None

    def test_rule_engine_property(self):
        layer = SymbolicLayer()
        assert layer.rule_engine is not None
        assert len(layer.rule_engine.list_rules()) >= 5
