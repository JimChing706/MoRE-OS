"""D-1 / D-2 / D-4 回归测试：判据统一、断言默认强制、阶段分段计时。"""

from __future__ import annotations

import pytest

from more_core.codegen.delivery_policy import resolve_delivery_decision
from more_core.codegen.escalation import EscalationCause, classify_escalation
from more_core.codegen.gates import derive_required_symbols

# ---------------------------------------------------------------------------
# D-1：升级原因分类 + 交付判据统一
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "checks,artifacts,expected",
    [
        (
            {"sandbox": False},
            {"last_error": "NameError: name 'x' is not defined"},
            EscalationCause.CODE_ERROR,
        ),
        (
            {"sandbox": False},
            {"last_error": "sandbox timeout", "timed_out": True},
            EscalationCause.SANDBOX_TIMEOUT,
        ),
        (
            {"sandbox": False},
            {"last_error": "unknown tool: python_exec"},
            EscalationCause.SANDBOX_UNAVAILABLE,
        ),
        (
            {"sandbox": True, "assertions": False, "stagnant": True},
            {"last_error": "AssertionError: missing symbol"},
            EscalationCause.ASSERTIONS_FAILED,
        ),
        ({"sandbox": True, "review": "rejected"}, {}, EscalationCause.REVIEW_REJECTED),
        ({"blocked": True}, {"violations": ["os.system"]}, EscalationCause.SAFETY_BLOCKED),
    ],
)
def test_escalation_cause_classification(checks, artifacts, expected):
    info = classify_escalation(decision="escalated", checks=checks, artifacts=artifacts)
    assert info.cause is expected
    assert info.is_blocking


def test_timeout_and_unavailable_are_infra_causes():
    t = classify_escalation(
        decision="escalated", checks={"sandbox": False}, artifacts={"last_error": "timed out"}
    )
    u = classify_escalation(
        decision="escalated", checks={"sandbox": False}, artifacts={"last_error": "unknown tool: x"}
    )
    assert t.is_infra and u.is_infra


def test_pass_has_no_cause():
    info = classify_escalation(decision="pass", checks={"sandbox": True}, artifacts={})
    assert info.cause is EscalationCause.NONE
    assert not info.is_blocking


@pytest.mark.parametrize(
    "cause,blocked,infra",
    [
        ("code_error", True, False),
        ("sandbox_unavailable", True, True),
        ("sandbox_timeout", True, True),
        ("assertions_failed", True, False),
        ("", True, False),
    ],
)
def test_delivery_decision_blocks_all_escalation_causes(cause, blocked, infra):
    d = resolve_delivery_decision(
        task_succeeded=True, gates_passed=True, verdict="escalated", cause=cause
    )
    assert (d.status == "blocked") is blocked
    assert d.is_infra is infra
    assert d.needs_attention is True


def test_delivery_decision_delivers_when_all_signals_pass():
    d = resolve_delivery_decision(task_succeeded=True, gates_passed=True, verdict="pass")
    assert d.status == "delivered"
    assert d.cause == "none"


def test_controller_records_cause_in_artifacts():
    from more_core.codegen.controller import adjudicate_codegen
    from more_core.tools.registry import ToolResult

    verdict = adjudicate_codegen(
        {
            "sandbox_result": ToolResult(
                tool="python_exec",
                success=False,
                output="",
                error="NameError: name 'x' is not defined",
            ),
            "code_fix_iterations": 3,
        },
        scope="code",
        sbx_success=False,
        max_rounds=3,
        assertions_required=False,
        run_ctx=None,
    )
    assert verdict.artifacts["cause"] == "code_error"
    assert "NameError" in verdict.artifacts["cause_detail"]
    assert any("cause=" in r for r in verdict.reasons)


# ---------------------------------------------------------------------------
# D-2：断言默认强制 + 精确符号派生
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("实现函数 merge_intervals(intervals) 合并区间", ["merge_intervals"]),
        ("写一个 `LRUCache` 类", ["LRUCache"]),
        ("实现 def transfer(a, b) 转账", ["transfer"]),
        ("写一段优雅的代码，注意可读性", []),  # 无代码式符号 → 不派生
        ("调用 print(x) 输出", []),  # 排除内置函数
    ],
)
def test_derive_required_symbols_is_conservative(query, expected):
    assert derive_required_symbols(query) == expected


def test_assertions_default_on_when_symbols_derivable():
    from more_core.layers.l0_execution import ExecutionLayer

    got = ExecutionLayer._resolve_assertions({}, "实现 leftpad(s, n) 函数")
    assert got and len(got) == 1 and "leftpad" in got[0]


def test_assertions_explicit_wins_and_can_be_disabled():
    from more_core.layers.l0_execution import ExecutionLayer

    assert ExecutionLayer._resolve_assertions({"assertions": ["assert f() == 1"]}, "f()") == [
        "assert f() == 1"
    ]
    assert ExecutionLayer._resolve_assertions({"require_assertions": False}, "f()") is None


def test_assertions_none_when_nothing_derivable():
    from more_core.layers.l0_execution import ExecutionLayer

    assert ExecutionLayer._resolve_assertions({}, "写一段优雅的代码") is None


# ---------------------------------------------------------------------------
# D-4：阶段分段计时
# ---------------------------------------------------------------------------


def test_ledger_stores_stage_timings(tmp_path):
    from more_core.codegen.delivery_ledger import DeliveryLedger

    led = DeliveryLedger(tmp_path / "l.db")
    led.record(
        task_id="t1",
        status="delivered",
        task_type="code_generation",
        stage_timings={"L4": 120.5, "L1": 30.0, "L0": 800.0},
    )
    rec = led.latest("t1")
    assert rec.stage_timings["L0"] == 800.0
    led.close()


def test_ledger_aggregates_stage_percentiles(tmp_path):
    from more_core.codegen.delivery_ledger import DeliveryLedger

    led = DeliveryLedger(tmp_path / "l.db")
    for i, l0 in enumerate([100.0, 300.0, 200.0]):
        led.record(task_id=f"t{i}", status="delivered", stage_timings={"L0": l0, "L4": 50.0})
    stats = led.stats(86400)
    assert stats["stage_ms_p50"]["L0"] == 200.0
    assert stats["stage_ms_p50"]["L4"] == 50.0
    led.close()


def test_stats_exposes_blocked_by_cause_and_infra(tmp_path):
    from more_core.codegen.delivery_ledger import DeliveryLedger

    led = DeliveryLedger(tmp_path / "l.db")
    led.record(task_id="ok", status="delivered")
    led.record(task_id="b1", status="blocked", gates_passed=True, cause="code_error")
    led.record(
        task_id="b2",
        status="blocked",
        gates_passed=True,
        cause="sandbox_unavailable",
        is_infra=True,
    )
    stats = led.stats(86400)
    assert stats["blocked_by_cause"] == {"code_error": 1, "sandbox_unavailable": 1}
    assert stats["infra_blocked"] == 1
    led.close()


# ---------------------------------------------------------------------------
# D-1 端到端：闸门拦截必须记录可聚合的 cause（此前的 unspecified 缺口）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_block_records_cause_end_to_end(tmp_path, monkeypatch):
    from more_core.codegen.delivery_ledger import DeliveryLedger, set_default_ledger
    from more_core.core.config import Settings
    from more_core.core.types import TaskRequest, TaskType
    from more_core.llm.provider import LLMResponse
    from more_core.runtime.orchestrator import MoRECore

    class _BrokenLLM:
        """返回语法被破坏的代码 → 必然被 syntax 闸门拦截。"""

        async def generate(self, req, **kw):
            return LLMResponse(
                content="```python\nsorted(xs, [REDACTED] k: k)\n```",
                provider="fake",
                model="m",
                prompt_tokens=100,
                completion_tokens=200,
                latency_ms=5.0,
            )

        async def health(self):
            return True

        def list_models(self):
            return ["m"]

        def list_providers(self):
            return ["fake"]

    ledger = DeliveryLedger(tmp_path / "ledger.db")
    set_default_ledger(ledger)
    monkeypatch.setenv("MORE_DELIVERY_LEDGER_DB", str(tmp_path / "ledger.db"))

    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
        codegen_candidates=1,
        codegen_review=False,
    )
    core = MoRECore(settings)
    core.llm = _BrokenLLM()

    result = await core.execute(
        TaskRequest(type=TaskType.CODE_GENERATION, query="实现 f(x) 只输出代码", timeout_s=60)
    )
    md = result.metadata or {}
    assert (md.get("delivery_gates") or {}).get("passed") is False

    escalation = md.get("escalation") or {}
    assert escalation.get("cause") == "gate_syntax_failed"
    assert escalation.get("is_infra") is False

    rec = ledger.latest(result.task_id)
    assert rec is not None and rec.status == "blocked"
    assert rec.cause == "gate_syntax_failed"
    # D-4：闸门拦截路径同样有分层耗时
    assert rec.stage_timings.get("L0") is not None

    set_default_ledger(None)
    ledger.close()


# ---------------------------------------------------------------------------
# 生产效率事故回归：断言不得被二次包裹成非法语法
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "assertions",
    [
        ["callable(globals().get('f'))"],  # 表达式
        ["assert f() == 1"],  # 完整语句
        ["assert f() == 1, 'msg'"],  # 带消息的完整语句
    ],
)
def test_verification_program_is_always_parsable(assertions):
    import ast

    from more_core.layers.l0_execution import ExecutionLayer

    program = ExecutionLayer._build_verification_program("def f():\n    return 1", assertions)
    ast.parse(program)  # 语法非法会直接抛 SyntaxError


def test_assertion_expression_not_double_wrapped():
    from more_core.layers.l0_execution import ExecutionLayer

    program = ExecutionLayer._build_verification_program(
        "def f():\n    return 1", ["callable(globals().get('f'))"]
    )
    assert "assert (assert" not in program
    assert program.count("assert ") == 1


def test_derived_assertions_are_expressions():
    """D-2 派生必须产出表达式，交由拼接器统一包装。"""
    from more_core.layers.l0_execution import ExecutionLayer

    got = ExecutionLayer._resolve_assertions({}, "实现 leftpad(s, n) 函数")
    assert got and all(not a.startswith("assert") for a in got)
