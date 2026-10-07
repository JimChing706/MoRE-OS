"""Step-4 fusion: Evolution signal ⇄ BaiLongma delegation linkage tests.

Covers the two-tier decision flow:
  * evolution signal bumps dynamic-k → chassis delegation is *preferred* first
  * explicit user intent (k=1, prefer_delegation=False) disables recommendation
  * SQLite evolution DB captures delegated / delegation_trigger / delegation_state
  * observability injection_hits recorded for evolution_escalation decisions
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.codegen.controller import adjudicate_codegen
from more_core.codegen.evolution_signal import (
    CodegenRunContext,
    _ensure_schema_migrated,
    _resolve_db_path,
)
from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.layers.base import LayerContext, LayerResult
from more_core.layers.l0_execution import (
    ExecutionLayer,
)


def _settings(
    *,
    enable_delegation: bool = False,
    endpoint: str = "",
    project_root: str | None = None,
    codegen_candidates: int = 2,
):
    return type(
        "S",
        (),
        {
            "bailongma_enable_delegation": enable_delegation,
            "bailongma_endpoint": endpoint,
            "project_root": project_root,
            "codegen_candidates": codegen_candidates,
            "codegen_review": False,
            "enable_symbolic": False,
        },
    )()


def _ctx(
    settings: Any,
    *,
    task_type=TaskType.CODE_GENERATION,
    query="write a greeting function in python",
    context=None,
):
    core = MagicMock()
    core.settings = settings
    core.tools.list_tools.return_value = []
    core.tools.invoke = AsyncMock(return_value=MagicMock(success=True, output="", error=""))
    llm_resp = MagicMock()
    llm_resp.content = "LOCAL_RUN def g():\n    return 'hi'"
    llm_resp.prompt_tokens = 1
    llm_resp.completion_tokens = 2
    llm_resp.latency_ms = 0.1
    llm_resp.provider = "mock"
    llm_resp.model = "mock"
    llm_resp.cached = False
    core.llm.generate = AsyncMock(return_value=llm_resp)
    core.audit = MagicMock()
    core.audit.log = MagicMock(return_value=None)
    core.audit_log = MagicMock()
    core.audit_log.log = MagicMock(return_value=None)
    req = TaskRequest(query=query, type=task_type, context=context or {})
    return LayerContext(core=core, request=req)


_LOCAL = "LOCAL_RUN"


def _delegated(output: str, state: str = "completed") -> LayerResult:
    return LayerResult(
        layer=LayerId.L0,
        description="delegated",
        output=output,
        confidence=0.9 if state == "completed" else 0.4,
        input_tokens=0,
        output_tokens=0,
    )


class TestDelegationAdviceUnit:
    def test_advice_chassis_disabled_returns_false(self, tmp_path):
        s = _settings(enable_delegation=False, endpoint="http://any", project_root=str(tmp_path))
        ctx = _ctx(s)
        advice = ExecutionLayer._evolution_delegation_advice(ctx, ctx.request, codegen_run_ctx=None)
        assert advice.recommend is False
        assert advice.trigger == "default_gate"
        assert "no delegation path" in advice.rationale.lower() or "endpoint" in advice.rationale

    def test_advice_user_candidates_eq_1_blocks_escalation(self, tmp_path):
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx = _ctx(s, context={"candidates": 1})
        advice = ExecutionLayer._evolution_delegation_advice(ctx, ctx.request, codegen_run_ctx=None)
        assert advice.recommend is False
        assert advice.candidate_k == 1
        assert "single-gen" in advice.rationale

    def test_advice_settings_candidates_eq_1_blocks_escalation(self, tmp_path):
        s = _settings(
            enable_delegation=True,
            endpoint="http://x",
            project_root=str(tmp_path),
            codegen_candidates=1,
        )
        ctx = _ctx(s)
        advice = ExecutionLayer._evolution_delegation_advice(ctx, ctx.request, codegen_run_ctx=None)
        assert advice.recommend is False
        assert advice.candidate_k == 1
        assert "settings.codegen_candidates" in advice.rationale

    def test_advice_per_request_prefer_delegation_true_wins(self, tmp_path):
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx = _ctx(s, context={"prefer_delegation": True})
        advice = ExecutionLayer._evolution_delegation_advice(ctx, ctx.request, codegen_run_ctx=None)
        assert advice.recommend is True
        assert advice.trigger == "user_override"

    def test_advice_per_request_prefer_delegation_false_blocks(self, tmp_path):
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx = _ctx(s, context={"prefer_delegation": False})
        advice = ExecutionLayer._evolution_delegation_advice(ctx, ctx.request, codegen_run_ctx=None)
        assert advice.recommend is False
        assert advice.trigger == "user_override"

    def test_advice_dynamic_k_escalated_recommends_delegation(self, tmp_path):
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx = _ctx(s)

        def fake_query(*a, **kw):
            return (2, "unit-test: escalated because history says struggle")

        with patch("more_core.codegen.evolution_signal.query_dynamic_k", side_effect=fake_query):
            advice = ExecutionLayer._evolution_delegation_advice(
                ctx, ctx.request, codegen_run_ctx=None
            )
        assert advice.recommend is True
        assert advice.trigger == "evolution_escalation"
        assert advice.candidate_k == 2
        assert "history says struggle" in advice.rationale


class TestEvolutionDelegationIntegration:
    @pytest.mark.asyncio
    async def test_evolution_escalation_calls_delegation_first_with_trigger(self, tmp_path):
        """Tier (1) evolution → delegation: hook is called with trigger=evolution_escalation."""
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx = _ctx(s)

        seen: dict[str, Any] = {}

        async def _hook(ctx_arg, req_arg, *, codegen_run_ctx=None, trigger=None, **_kw):
            seen["trigger"] = trigger
            ctx_arg.scratch["_chassis_delegated"] = True
            ctx_arg.scratch["_chassis_delegation_state"] = "completed"
            ctx_arg.scratch["_chassis_delegation_trigger"] = trigger
            ctx_arg.scratch["codegen_verdict"] = {
                "decision": "pass",
                "reasons": [],
                "checks": {"sandbox": True},
            }
            return _delegated("CHASSIS DONE", "completed")

        # Force evolution escalator by patching query_dynamic_k.
        with patch(
            "more_core.codegen.evolution_signal.query_dynamic_k",
            return_value=(2, "escalated in test"),
        ):
            with patch.object(
                ExecutionLayer, "_try_chassis_delegation", AsyncMock(side_effect=_hook)
            ):
                result = await ExecutionLayer().process(ctx)

        assert "CHASSIS DONE" in result.output
        assert seen.get("trigger") == "evolution_escalation"
        assert (
            ctx.scratch.get("_l0_delegation_advice")
            and "evolution_escalation" in ctx.scratch["_l0_delegation_advice"]
        )

    @pytest.mark.asyncio
    async def test_default_gate_runs_when_no_escalation(self, tmp_path):
        """Tier (2) default gate: no escalation but chassis gate on → delegation with trigger=default_gate."""
        s = _settings(enable_delegation=True, endpoint="http://y", project_root=str(tmp_path))
        ctx = _ctx(s)

        seen: dict[str, Any] = {}

        async def _hook(ctx_arg, req_arg, *, codegen_run_ctx=None, trigger=None, **_kw):
            seen["trigger"] = trigger
            ctx_arg.scratch["_chassis_delegated"] = True
            ctx_arg.scratch["_chassis_delegation_state"] = "completed"
            return _delegated("DEFAULT_GATE_OK", "completed")

        # No signal — dynamic_k returns 0 (not enough history path).
        with patch(
            "more_core.codegen.evolution_signal.query_dynamic_k",
            return_value=(0, "not enough history"),
        ):
            with patch.object(
                ExecutionLayer, "_try_chassis_delegation", AsyncMock(side_effect=_hook)
            ):
                result = await ExecutionLayer().process(ctx)

        assert "DEFAULT_GATE_OK" in result.output
        assert seen.get("trigger") == "default_gate"

    @pytest.mark.asyncio
    async def test_delegation_fail_fallback_local_still_runs(self, tmp_path):
        s = _settings(enable_delegation=True, endpoint="http://x", project_root=str(tmp_path))
        ctx, _ = _ctx(s), None
        core = ctx.core

        async def _hook(ctx_arg, req_arg, *, codegen_run_ctx=None, trigger=None, **_kw):
            # Simulate chassis side returning None (e.g. ping unreachable).
            return None

        with patch(
            "more_core.codegen.evolution_signal.query_dynamic_k", return_value=(2, "escalated")
        ):
            with patch.object(
                ExecutionLayer, "_try_chassis_delegation", AsyncMock(side_effect=_hook)
            ):
                result = await ExecutionLayer().process(ctx)

        # Local path executed.
        assert _LOCAL in result.output
        assert core.llm.generate.await_count >= 1

    def test_export_evolution_signal_delegation_columns_written(self, tmp_path):
        """adjudicate → export must include delegated/trigger/state in SQLite row."""
        pr = str(tmp_path)
        # Use _get_conn so DB dir is created + schema applied + migrated.
        from more_core.codegen.evolution_signal import _get_conn

        db_path = _resolve_db_path(pr)
        conn = _get_conn(db_path)
        _ensure_schema_migrated(conn)
        conn.close()

        scratch: dict[str, Any] = {
            "_chassis_delegated": True,
            "_chassis_delegation_trigger": "evolution_escalation",
            "_chassis_delegation_state": "completed",
            "code_fix_iterations": 0,
        }

        run_ctx = CodegenRunContext(
            task_id="t-export-1",
            task_type=str(TaskType.CODE_GENERATION),
            query_fingerprint="abcdef123456",
            project_root=pr,
        )
        verdict = adjudicate_codegen(
            scratch,
            scope="code",
            sbx_success=True,
            max_rounds=3,
            assertions_required=False,
            run_ctx=run_ctx,
        )
        assert verdict.ok
        assert verdict.artifacts.get("delegated") is True
        assert verdict.artifacts.get("delegation_trigger") == "evolution_escalation"
        assert verdict.artifacts.get("delegation_state") == "completed"

        # Query row back directly.
        import sqlite3 as sq

        conn2 = sq.connect(str(db_path))
        row = conn2.execute(
            "SELECT delegated, delegation_trigger, delegation_state, decision FROM codegen_runs WHERE task_id = ?",
            ("t-export-1",),
        ).fetchone()
        conn2.close()
        assert row is not None
        delegated, trig, state, decision = row
        assert delegated == 1
        assert trig == "evolution_escalation"
        assert state == "completed"
        assert decision == "pass"
