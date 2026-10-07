"""Step-4 P1: L0 codegen chassis delegation tests.

Uses unittest.mock.patch with ``side_effect`` factory so
``self._try_chassis_delegation(...)`` from inside ``process()`` correctly
binds and returns the substituted value.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskType
from more_core.layers.base import LayerContext, LayerResult
from more_core.layers.l0_execution import ExecutionLayer


def _mk_settings(
    *,
    enabled: bool = False,
    endpoint: str = "",
    codegen_review: bool = False,
    codegen_candidates: int = 1,
):
    return type(
        "S",
        (),
        {
            "bailongma_enable_delegation": enabled,
            "bailongma_endpoint": endpoint,
            "codegen_review": codegen_review,
            "codegen_candidates": codegen_candidates,
            "enable_symbolic": False,
        },
    )()


def _mk_ctx(
    settings: Any,
    *,
    task_type: TaskType = TaskType.CODE_GENERATION,
    query: str = "write me a fibonacci function in Python",
    context: dict[str, Any] | None = None,
):
    core = MagicMock()
    core.settings = settings
    core.tools.list_tools.return_value = []
    core.tools.invoke = AsyncMock(return_value=MagicMock(success=True, output="", error=""))
    llm_resp = MagicMock()
    llm_resp.content = "LOCAL GENERATION HAPPENED: def fib(n):\n    return 1"
    llm_resp.prompt_tokens = 2
    llm_resp.completion_tokens = 3
    llm_resp.latency_ms = 0.5
    llm_resp.provider = "mock"
    llm_resp.model = "mock"
    llm_resp.cached = False
    core.llm.generate = AsyncMock(return_value=llm_resp)
    core.audit = MagicMock()
    core.audit.log = MagicMock(return_value=None)
    audit_table = MagicMock()
    audit_table.log = MagicMock(return_value=None)
    core.audit_log = audit_table
    req = TaskRequest(query=query, type=task_type, context=context or {})
    ctx = LayerContext(core=core, request=req)
    return ctx, core.llm.generate


_LOCAL = "LOCAL GENERATION HAPPENED"


def _chassis_layer_result(output: str, state: str) -> LayerResult:
    return LayerResult(
        layer=LayerId.L0,
        description="LLM generation + chassis delegated",
        output=output,
        confidence=0.9 if state == "completed" else 0.4,
        input_tokens=0,
        output_tokens=0,
    )


def _patch_with_side_effect(side_effect_fn):
    """Patch ``ExecutionLayer._try_chassis_delegation`` with an ``AsyncMock``
    whose ``side_effect`` is ``side_effect_fn``.

    Accepts **kwargs so the helper stays compatible across signature
    extensions (``trigger=``, etc).
    """
    m = AsyncMock()
    m.side_effect = side_effect_fn
    return patch.object(ExecutionLayer, "_try_chassis_delegation", m), m


@pytest.mark.asyncio
async def test_disabled_flag_delegation_returns_none_local_runs():
    # With the REAL _try_chassis_delegation (not patched), enabled=False
    # → None is returned, and local LLM is used.
    s = _mk_settings(enabled=False, endpoint="http://any")
    ctx, llm_mock = _mk_ctx(s)
    result = await ExecutionLayer().process(ctx)
    assert _LOCAL in result.output
    assert llm_mock.await_count >= 1


@pytest.mark.asyncio
async def test_enabled_gate_calls_delegation_fn_once():
    s = _mk_settings(enabled=True, endpoint="http://reachable")
    ctx, llm_mock = _mk_ctx(s)
    calls = []

    async def _capture(ctx_arg, req_arg, *, codegen_run_ctx=None, **_kw):
        calls.append(True)

    p, _m = _patch_with_side_effect(_capture)
    with p:
        result = await ExecutionLayer().process(ctx)
    assert len(calls) == 1
    assert llm_mock.await_count >= 1
    assert _LOCAL in result.output


@pytest.mark.asyncio
async def test_delegation_success_short_circuits_no_local_llm():
    s = _mk_settings(enabled=True, endpoint="http://reachable")
    ctx, llm_mock = _mk_ctx(s)

    async def _success(ctx_arg, req_arg, *, codegen_run_ctx=None, **_kw):
        ctx_arg.scratch["_chassis_delegated"] = True
        ctx_arg.scratch["_chassis_delegation_state"] = "completed"
        ctx_arg.scratch["_chassis_task_id"] = "stub-1"
        ctx_arg.scratch["codegen_verdict"] = {
            "decision": "pass",
            "reasons": ["chassis_delegation"],
            "checks": {"sandbox": True},
        }
        return _chassis_layer_result("CHASSIS RESULT: OK", "completed")

    p, _m = _patch_with_side_effect(_success)
    with p:
        result = await ExecutionLayer().process(ctx)
    assert llm_mock.await_count == 0
    assert "CHASSIS RESULT: OK" in result.output
    assert ctx.scratch["_chassis_delegated"] is True
    assert ctx.scratch["_chassis_task_id"] == "stub-1"
    assert ctx.scratch["codegen_verdict"]["decision"] == "pass"


@pytest.mark.asyncio
async def test_delegation_partial_verdict_no_local_fallback():
    s = _mk_settings(enabled=True, endpoint="http://reachable")
    ctx, llm_mock = _mk_ctx(s)

    async def _partial(ctx_arg, req_arg, *, codegen_run_ctx=None, **_kw):
        ctx_arg.scratch["_chassis_delegated"] = True
        ctx_arg.scratch["_chassis_delegation_state"] = "failed"
        ctx_arg.scratch["codegen_verdict"] = {
            "decision": "partial",
            "reasons": ["chassis_timeout"],
            "checks": {"sandbox": False},
        }
        return _chassis_layer_result("CHASSIS FAILED: timeout", "failed")

    p, _m = _patch_with_side_effect(_partial)
    with p:
        result = await ExecutionLayer().process(ctx)
    assert llm_mock.await_count == 0
    assert "CHASSIS FAILED" in result.output
    assert ctx.scratch["codegen_verdict"]["decision"] == "partial"


@pytest.mark.asyncio
async def test_non_code_task_never_invokes_delegation_fn():
    s = _mk_settings(enabled=True, endpoint="http://reachable")
    ctx, llm_mock = _mk_ctx(s, task_type=TaskType.NLP_TASK, query="what is a cow")
    call_count = {"n": 0}

    async def _count(ctx_arg, req_arg, *, codegen_run_ctx=None, **_kw):
        call_count["n"] += 1

    p, _m = _patch_with_side_effect(_count)
    with p:
        result = await ExecutionLayer().process(ctx)
    assert call_count["n"] == 0
    assert llm_mock.await_count >= 1
    assert _LOCAL in result.output


@pytest.mark.asyncio
async def test_delegation_fn_raises_no_propagation():
    s = _mk_settings(enabled=True, endpoint="http://reachable")
    ctx, llm_mock = _mk_ctx(s)

    async def _boom(ctx_arg, req_arg, *, codegen_run_ctx=None, **_kw):
        raise RuntimeError("any transport failure!")

    p, _m = _patch_with_side_effect(_boom)
    with p:
        # process() wraps the delegation call in try/except.  Must not raise.
        result = await ExecutionLayer().process(ctx)
    assert llm_mock.await_count >= 1
    assert _LOCAL in result.output


@pytest.mark.asyncio
async def test_all_code_family_types_short_circuit_on_success():
    for t in (TaskType.CODE_DEBUGGING, TaskType.CODE_TESTING, TaskType.CODE_REVIEW):
        s = _mk_settings(enabled=True, endpoint="http://reachable")
        ctx, llm_mock = _mk_ctx(s, task_type=t, query=f"{t.value} task")

        async def _success_for(ctx_arg, req_arg, *, codegen_run_ctx=None, _t=t, **_kw):
            ctx_arg.scratch["_chassis_delegated"] = True
            ctx_arg.scratch["_chassis_delegation_state"] = "completed"
            ctx_arg.scratch["codegen_verdict"] = {"decision": "pass", "reasons": [], "checks": {}}
            return _chassis_layer_result(f"CHASSIS FOR {_t.value}", "completed")

        p, _m = _patch_with_side_effect(_success_for)
        with p:
            result = await ExecutionLayer().process(ctx)
        # Delegation short-circuited — zero local LLM calls.
        assert llm_mock.await_count == 0
        assert f"CHASSIS FOR {t.value}" in result.output
        assert ctx.scratch["_chassis_delegation_state"] == "completed"
