"""评估阶段 G1/G2 回归测试：交付状态交叉校验 + 延迟分位口径。"""

from __future__ import annotations

import pytest

from more_core.codegen.delivery_policy import resolve_delivery_status


# ---------------------------------------------------------------------------
# G1：闸门结论 × 控制器裁决 的交叉校验
# ---------------------------------------------------------------------------


def test_delivered_when_all_signals_agree():
    status, reason = resolve_delivery_status(task_succeeded=True, gates_passed=True, verdict="pass")
    assert status == "delivered"
    assert reason == ""


@pytest.mark.parametrize("verdict", ["escalated"])
def test_blocked_when_controller_escalated_even_if_gates_pass(verdict):
    """核心回归：控制器说"成功判据未满足"，就绝不能记为已交付。"""
    status, reason = resolve_delivery_status(
        task_succeeded=True, gates_passed=True, verdict=verdict
    )
    assert status == "blocked"
    assert "escalated" in reason


def test_blocked_when_gates_fail():
    status, reason = resolve_delivery_status(
        task_succeeded=True, gates_passed=False, verdict="pass"
    )
    assert status == "blocked"
    assert "gates" in reason


def test_failed_when_task_failed():
    status, _ = resolve_delivery_status(task_succeeded=False, gates_passed=True, verdict="")
    assert status == "failed"


def test_partial_verdict_is_deliverable():
    """partial = 仅 P3（可读性类）问题，允许交付。"""
    status, _ = resolve_delivery_status(task_succeeded=True, gates_passed=True, verdict="partial")
    assert status == "delivered"


# ---------------------------------------------------------------------------
# G2：延迟分位口径（排除缓存与失败样本）
# ---------------------------------------------------------------------------


@pytest.fixture()
def obs(tmp_path, monkeypatch):
    from more_core.governance import observability as module

    module.configure(tmp_path / "obs.sqlite")
    yield module
    module.close()


def _call(obs, rid, latency, success=True, cached=False):
    obs.record_llm_call(
        request_id=rid,
        provider="p",
        model="m",
        prompt_chars=1,
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=latency,
        success=success,
        cached=cached,
    )


def test_latency_percentiles_exclude_cached_and_failed(obs):
    _call(obs, "cached", 0.0, success=True, cached=True)
    _call(obs, "failed1", 0.0, success=False)
    _call(obs, "failed2", 0.0, success=False)
    _call(obs, "ok1", 800.0)
    _call(obs, "ok2", 1200.0)

    m = obs.summary(3600)
    assert m["samples"] == 5
    assert m["measured_calls"] == 2  # 成功且非缓存
    assert m["cached_calls"] == 1
    assert m["failed_calls"] == 2
    assert m["latency_ms"]["p50"] == 800.0
    assert m["latency_ms"]["max"] == 1200.0


def test_latency_falls_back_when_no_successful_sample(obs):
    """全是失败/缓存时不应崩，退化为全量样本。"""
    _call(obs, "failed", 0.0, success=False)
    _call(obs, "cached", 0.0, success=True, cached=True)
    m = obs.summary(3600)
    assert m["measured_calls"] == 0
    assert m["latency_ms"]["max"] == 0.0


def test_token_totals_include_all_calls(obs):
    """token 口径不受延迟口径影响：成功/失败/缓存都计入消耗。"""
    _call(obs, "a", 10.0)
    _call(obs, "b", 0.0, success=False)
    _call(obs, "c", 0.0, success=True, cached=True)
    m = obs.summary(3600)
    assert m["tokens"]["total"] == 6


# ---------------------------------------------------------------------------
# R-20：escalated 结论必须可诊断（保留沙箱失败原因）
# ---------------------------------------------------------------------------


def test_escalated_verdict_carries_sandbox_failure_reason():
    from more_core.codegen.controller import adjudicate_codegen
    from more_core.tools.registry import ToolResult

    scratch = {
        "code_fix_iterations": 3,
        "sandbox_result": ToolResult(
            tool="python_exec",
            success=False,
            output="Traceback (most recent call last):\nNameError: name 'x' is not defined",
            error="NameError: name 'x' is not defined",
        ),
    }
    verdict = adjudicate_codegen(
        scratch,
        scope="code",
        sbx_success=False,
        max_rounds=3,
        assertions_required=False,
        run_ctx=None,
    )
    assert verdict.decision == "escalated"
    assert "NameError" in verdict.artifacts["last_error"]
    assert verdict.artifacts["timed_out"] is False


def test_escalated_verdict_marks_timeout():
    from types import SimpleNamespace

    from more_core.codegen.controller import adjudicate_codegen

    # 用最小对象模拟带 timed_out 的沙箱结果（ToolResult 无该字段）
    scratch = {
        "sandbox_result": SimpleNamespace(
            success=False,
            output="",
            error="sandbox timeout",
            timed_out=True,
        ),
    }
    verdict = adjudicate_codegen(
        scratch,
        scope="code",
        sbx_success=False,
        max_rounds=3,
        assertions_required=False,
        run_ctx=None,
    )
    assert verdict.artifacts["timed_out"] is True
    assert "timeout" in verdict.artifacts["last_error"]
