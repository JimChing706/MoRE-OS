#!/usr/bin/env python3
"""离线自检：验证提取后的 Code Shop 包**在没有外部模型时**依然可用。

检查项：
  1. 内核可导入（提取完整、相对导入未破坏）
  2. 多维闸门行为正确（语法/逻辑/需求）
  3. 端到端：假 LLM → 生成 → 闸门 → 交付台账（离线可复现）
  4. 运行指标与交付统计接口可用
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT / "src"))

PASS = FAIL = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(("  ✓ " if ok else "  ✗ ") + name + (f"   [{extra}]" if extra else ""))


def _check_imports() -> None:
    print("\n[1] 内核提取完整性")
    from more_core.codegen import delivery_ledger, delivery_policy, escalation, gates  # noqa: F401
    from more_core.governance import observability  # noqa: F401
    from more_core.llm import preflight  # noqa: F401
    from more_core.runtime.orchestrator import MoRECore  # noqa: F401
    from more_core.sandbox import policy, secure_sandbox  # noqa: F401

    check("核心模块可导入（codegen/llm/sandbox/observability）", True)
    n = len(list((PKG_ROOT / "src" / "more_core").rglob("*.py")))
    check("提取到内核源文件", n > 150, f"{n} 个 .py")


def _check_gates() -> None:
    print("\n[2] 多维闸门")
    from more_core.codegen.gates import syntax_gate, logic_gate, requirement_gate

    good = '```python\ndef f(x):\n    return x * 2\n```'
    broken = '```python\nsorted(xs, [REDACTED] k: k)\n```'
    stub = '```rust\nfn main(){ println!("placeholder"); }\n```'
    check("语法闸门：合法代码通过", syntax_gate(good).ok)
    check("语法闸门：语法错误被拦", not syntax_gate(broken).ok)
    check("逻辑闸门：占位实现被拦", not logic_gate(stub).ok)
    ok = requirement_gate(good, "实现函数 f(x)").ok
    check("需求匹配：符号覆盖判定", ok)


async def _check_end_to_end() -> None:
    print("\n[3] 端到端（假 LLM，离线）")
    import os

    tmp = Path(tempfile.mkdtemp())
    os.environ["MORE_DELIVERY_LEDGER_DB"] = str(tmp / "ledger.db")

    from more_core.codegen.delivery_ledger import DeliveryLedger, set_default_ledger
    from more_core.core.config import Settings
    from more_core.core.types import TaskRequest, TaskType
    from more_core.llm.provider import LLMResponse
    from more_core.runtime.orchestrator import MoRECore

    class _FakeLLM:
        async def generate(self, req, **kw):  # noqa: ANN001
            return LLMResponse(
                content='```python\ndef double(x):\n    return x * 2\n```',
                provider="fake", model="fake-1",
                prompt_tokens=100, completion_tokens=200, latency_ms=5.0,
            )

        async def health(self):
            return True

        def list_models(self):
            return ["fake-1"]

        def list_providers(self):
            return ["fake"]

    ledger = DeliveryLedger(tmp / "ledger.db")
    set_default_ledger(ledger)
    settings = Settings(providers=[], fallback_chain=[], enable_evolution=False,
                        enable_metacognition=False, enable_symbolic=True,
                        codegen_candidates=1, codegen_review=False)
    core = MoRECore(settings)
    core.llm = _FakeLLM()
    # 离线注册内置工具（等价于生产 start() 的第一步）：
    # 不注册则代码任务永远进不了沙箱，Controller 会因 sandbox=False 判 escalated
    # 而被正确拦截 —— 那是自检夹具缺陷，不是产品缺陷。
    from more_core.tools.builtins import register_builtins

    register_builtins(core.tools, core)

    result = await core.execute(TaskRequest(
        type=TaskType.CODE_GENERATION, query="实现函数 double(x) 返回 x*2", timeout_s=60))
    md = result.metadata or {}
    gates = md.get("delivery_gates") or {}
    stages = (md.get("stage_timings") or {}).get("layers_ms") or {}

    check("任务成功", str(getattr(result.status, "value", result.status)) == "success",
          str(getattr(result.status, "value", result.status)))
    check("闸门通过", bool(gates.get("passed")))
    check("阶段分段计时已采集", bool(stages), str(stages))
    rec = ledger.latest(result.task_id)
    check("交付台账已记录", rec is not None and len(rec.artifact_sha256) == 64,
          f"status={rec.status if rec else None}")
    set_default_ledger(None)
    ledger.close()


def _check_facade() -> None:
    print("\n[4] 产品门面 / 指标接口")
    try:
        from qnming_code_shop import __version__
        from qnming_code_shop.facade import delivery_stats, metrics  # noqa: F401

        check("产品包可导入", bool(__version__), f"v{__version__}")
        check("指标/交付统计接口存在", callable(metrics) and callable(delivery_stats))
    except Exception as exc:  # pragma: no cover
        check("产品包可导入", False, str(exc)[:60])


def main() -> int:
    print("=" * 62)
    print("QNMing-MoRE-Code-Shop 离线自检")
    print("=" * 62)
    _check_imports()
    _check_gates()
    asyncio.run(_check_end_to_end())
    _check_facade()
    print("\n" + "=" * 62)
    print(f"结果: {PASS} passed / {FAIL} failed")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
