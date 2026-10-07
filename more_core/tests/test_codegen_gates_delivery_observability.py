"""三大硬伤修复的回归测试：产出正确性 / 交付可信度 / 可观测性。"""

from __future__ import annotations

import pytest

from more_core.codegen.gates import (
    extract_code_blocks,
    logic_gate,
    requirement_gate,
    run_gates,
    syntax_gate,
)
from more_core.security.output_filter import _DEFAULT_RULES, OutputFilter

GOOD_CODE = """```python
def merge_intervals(intervals):
    out = []
    for start, end in sorted(intervals, key=lambda x: x[0]):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out
```"""

BROKEN_CODE = """```python
sorted_intervals = sorted(intervals, [ENV_SECRET_REDACTED] x: x[0])
```"""

PLACEHOLDER = """```rust
fn main(){ println!("shooter server placeholder"); }
```"""


# ---------------------------------------------------------------------------
# 产出正确性：闸门
# ---------------------------------------------------------------------------


def test_extract_code_blocks_keeps_language_and_body():
    blocks = extract_code_blocks(GOOD_CODE)
    assert len(blocks) == 1
    assert blocks[0][0] == "python"
    assert "merge_intervals" in blocks[0][1]


def test_syntax_gate_passes_valid_python():
    finding = syntax_gate(GOOD_CODE)
    assert finding.ok and not finding.blocking


def test_syntax_gate_blocks_broken_python():
    finding = syntax_gate(BROKEN_CODE)
    assert not finding.ok and finding.blocking
    assert "syntax" in finding.detail.lower() or finding.evidence


def test_syntax_gate_checks_brace_languages():
    assert syntax_gate("```rust\nfn main() {}\n```").ok
    assert not syntax_gate("```rust\nfn main() {\n```").ok


def test_logic_gate_flags_placeholder_only_delivery():
    finding = logic_gate(PLACEHOLDER)
    assert not finding.ok and finding.blocking
    assert "占位" in finding.detail or "空壳" in finding.detail


def test_logic_gate_allows_real_implementation():
    assert logic_gate(GOOD_CODE).ok


def test_requirement_gate_measures_symbol_coverage():
    ok = requirement_gate(GOOD_CODE, "写函数 merge_intervals(intervals) 合并区间")
    assert ok.ok
    missing = requirement_gate(BROKEN_CODE, "写函数 merge_intervals(intervals) 合并区间")
    assert not missing.ok and missing.blocking


def test_run_gates_composes_and_reports():
    assert run_gates(GOOD_CODE, query="写函数 merge_intervals(intervals)").passed
    assert not run_gates(BROKEN_CODE, query="写函数 merge_intervals(intervals)").passed
    assert not run_gates(PLACEHOLDER, query="实现 shooter server", require_logic=True).passed


# ---------------------------------------------------------------------------
# 产出正确性：过滤器回归（F-01）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "sorted(items, key=lambda x: x[0])",
        "def f(key=1, token=None): pass",
        "redis.set(key=user_id, value=data)",
        "token = refresh_token",
        "password = hashed_password",
    ],
)
def test_output_filter_does_not_corrupt_python_keyword_arguments(source):
    assert OutputFilter().filter(source) == source


@pytest.mark.parametrize(
    "source",
    [
        'API_KEY = "sk-live-abcdef0123456789"',
        'password = "hunter2hunter2"',
        "SECRET: 'abcdefghijklmnop'",
    ],
)
def test_output_filter_still_redacts_real_secret_literals(source):
    assert OutputFilter().filter(source) != source


def test_env_secret_rule_is_the_regression_source():
    rule = next(r for r in _DEFAULT_RULES if r.name == "env_secret")
    assert not rule.pattern.search("sorted(x, key=lambda v: v)")
    assert rule.pattern.search('TOKEN = "abcdefghijklmnop"')


# ---------------------------------------------------------------------------
# 可观测性：token / 延迟采集
# ---------------------------------------------------------------------------


@pytest.fixture()
def obs(tmp_path, monkeypatch):
    from more_core.governance import observability as module

    monkeypatch.setenv("MORE_OBS_DB", str(tmp_path / "obs.sqlite"))
    module.configure(tmp_path / "obs.sqlite")
    yield module
    module.close()


def test_observability_store_is_reachable(obs):
    """回归：曾因 `from .config` 导入错误导致整条遥测静默失效。"""
    assert obs._get_conn() is not None


def test_llm_call_records_tokens_and_latency(obs):
    obs.record_llm_call(
        request_id="r1",
        provider="lmstudio",
        model="m1",
        prompt_chars=100,
        prompt_tokens=120,
        completion_tokens=80,
        latency_ms=250.0,
        success=True,
    )
    obs.record_llm_call(
        request_id="r2",
        provider="lmstudio",
        model="m1",
        prompt_chars=50,
        prompt_tokens=30,
        completion_tokens=20,
        latency_ms=750.0,
        success=False,
        error="timeout",
    )
    stats = obs.summary(3600)
    assert stats["samples"] == 2
    # token 口径不受成败影响：失败调用的消耗同样计入
    assert stats["tokens"]["total"] == 250
    assert stats["tokens"]["prompt"] == 150
    assert stats["tokens"]["completion"] == 100
    assert stats["success_rate"] == 0.5
    # G2：延迟分位只统计"成功且非缓存"的调用；失败样本以 latency=0 落库，
    # 若计入会把 p50 拉到 0，掩盖真实延迟分布。
    assert stats["measured_calls"] == 1  # 仅 r1 成功
    assert stats["failed_calls"] == 1  # r2 失败
    assert stats["latency_ms"]["avg"] == 250.0
    assert stats["latency_ms"]["max"] == 250.0
    assert stats["providers"]["lmstudio:m1"]["calls"] == 2


def test_observability_summary_empty_window(obs):
    stats = obs.summary(3600)
    assert stats["samples"] == 0
    assert "error" not in stats


def test_recent_llm_query_roundtrip(obs):
    obs.record_llm_call(
        request_id="r3",
        provider="ollama",
        model="qwen",
        prompt_chars=1,
        prompt_tokens=2,
        completion_tokens=3,
        latency_ms=10.0,
        success=True,
    )
    rows = obs.query_recent_llm(limit=10)
    assert rows and rows[0]["provider"] == "ollama"


# ---------------------------------------------------------------------------
# 交付可信度：台账 / 版本 / 成功率
# ---------------------------------------------------------------------------


@pytest.fixture()
def ledger(tmp_path):
    from more_core.codegen.delivery_ledger import DeliveryLedger

    led = DeliveryLedger(tmp_path / "ledger.db")
    yield led
    led.close()


def test_delivery_ledger_versions_per_task(ledger):
    first = ledger.record(task_id="t1", status="blocked", gates_passed=False)
    second = ledger.record(task_id="t1", status="delivered", gates_passed=True)
    assert (first.version, second.version) == (1, 2)
    history = ledger.list(task_id="t1")
    assert [h.status for h in history] == ["delivered", "blocked"]


def test_delivery_ledger_tracks_artifact_hash_and_actor(ledger):
    rec = ledger.record(
        task_id="t2",
        status="delivered",
        artifact="hello",
        actor="alice",
        provider="lmstudio",
        model="m",
        verdict="pass",
        gates={"passed": True},
        request_excerpt="写一个函数",
    )
    assert len(rec.artifact_sha256) == 64
    assert rec.actor == "alice" and rec.artifact_chars == 5
    assert rec.to_dict()["created_at"]


def test_delivery_success_rate_model(ledger):
    ledger.record(task_id="a", status="delivered", task_type="code_generation")
    ledger.record(task_id="b", status="delivered", task_type="code_generation")
    ledger.record(task_id="c", status="blocked", task_type="code_generation", gates_passed=False)
    ledger.record(task_id="d", status="failed", task_type="code_debugging")
    stats = ledger.stats(86400)
    assert stats["total"] == 4
    assert stats["delivered"] == 2
    assert stats["blocked"] == 1
    assert stats["failed"] == 1
    assert stats["success_rate"] == 0.5
    assert stats["by_task_type"]["code_generation"]["success_rate"] == pytest.approx(
        0.667, abs=0.001
    )
    assert stats["by_task_type"]["code_debugging"]["success_rate"] == 0.0


def test_delivery_ledger_latest_and_missing(ledger):
    ledger.record(task_id="x", status="blocked", gates_passed=False)
    ledger.record(task_id="x", status="delivered")
    assert ledger.latest("x").status == "delivered"
    assert ledger.latest("nope") is None
