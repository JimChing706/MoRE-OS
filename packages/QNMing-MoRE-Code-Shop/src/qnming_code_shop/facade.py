"""产品门面：把内核的代码生成链路包装成"一次调用即产出可信交付"的 API。

设计目标（对应三大硬伤整改成果）：

* **产出正确性**：交付前必经 ``codegen.gates`` 多维闸门（语法/逻辑/需求匹配）
* **交付可信度**：每次交付写入 ``codegen.delivery_ledger``（状态/权责/哈希/裁决/原因）
* **可观测性**：LLM 调用与阶段耗时自动入库，可通过 ``metrics()`` 查询
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["GenerateResult", "generate_code", "preflight", "metrics"]


@dataclass
class GenerateResult:
    """一次代码生成请求的完整结论。"""

    task_id: str
    status: str
    output: str
    gates: dict[str, Any]
    verdict: dict[str, Any]
    escalation: dict[str, Any]
    stage_timings: dict[str, Any]
    tokens_used: int
    delivery: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success" and bool((self.gates or {}).get("passed"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "ok": self.ok,
            "gates": self.gates,
            "verdict": self.verdict.get("decision") if self.verdict else None,
            "escalation": self.escalation,
            "stage_timings": self.stage_timings,
            "tokens_used": self.tokens_used,
            "delivery": self.delivery,
            "output": self.output,
        }


async def generate_code(
    query: str,
    *,
    actor: str = "code-shop",
    candidates: int = 1,
    timeout_s: float = 300.0,
    context: dict[str, Any] | None = None,
    core: Any = None,
) -> GenerateResult:
    """跑一次代码生成任务，返回带闸门/台账/耗时的完整结论。

    Args:
        query:      自然语言需求（例如 "实现 Python 函数 is_palindrome(s)"）。
        actor:      调用主体（写入交付台账的权责标记）。
        candidates: best-of-k 候选数（1 = 单路）。
        core:       可选：注入已构建的 MoRECore（测试/复用连接时使用）。
    """
    from more_core.core.types import TaskRequest, TaskType
    from more_core.runtime.orchestrator import MoRECore

    owns_core = core is None
    if owns_core:
        core = MoRECore.from_env()
        await core.start()
    try:
        req = TaskRequest(
            type=TaskType.CODE_GENERATION,
            query=query,
            context={**(context or {}), "actor": actor, "candidates": candidates},
            timeout_s=timeout_s,
        )
        result = await core.execute(req)
        md = result.metadata or {}
        perf = result.performance
        return GenerateResult(
            task_id=result.task_id,
            status=str(getattr(result.status, "value", result.status)),
            output=str(result.output or ""),
            gates=md.get("delivery_gates") or {},
            verdict=md.get("codegen_verdict") or {},
            escalation=md.get("escalation") or {},
            stage_timings=md.get("stage_timings") or {},
            tokens_used=int(getattr(perf, "tokens_used", 0) or 0),
        )
    finally:
        if owns_core:
            await core.stop()


async def preflight() -> dict[str, Any]:
    """LLM 链路预检：provider 注册 / 模型存在性 / 兜底链完整度。"""
    from more_core.llm.preflight import preflight_llm
    from more_core.runtime.orchestrator import MoRECore

    core = MoRECore.from_env()
    try:
        report = await preflight_llm(core.llm, list(getattr(core.llm, "_fallback", []) or []))
        return report.to_dict()
    finally:
        await core.stop()


def metrics(window_s: int = 3600) -> dict[str, Any]:
    """读取运行指标（token 消耗 / 请求延迟 / 成功率）。"""
    from more_core.governance import observability as obs

    return obs.summary(window_s)


def delivery_stats(window_s: int = 86400) -> dict[str, Any]:
    """读取交付成功率模型（含阻断原因分布与阶段耗时分位）。"""
    from more_core.codegen.delivery_ledger import get_default_ledger

    return get_default_ledger().stats(window_s)
