"""交付状态判定策略 —— 闸门结论与控制器裁决的交叉校验。

为什么需要它（评估阶段发现的 G1）：
交付状态与 Codegen Controller 裁决是两条独立信号，历史上未做一致性校验，
出现过 ``status=delivered`` 而 ``codegen_verdict=escalated`` 的自相矛盾记录
（控制器判定"成功判据未满足"，台账却记为"已交付"）。

本模块把判定收敛成一个纯函数，便于单测与复用：

    delivered  ← 任务成功 + 闸门通过 + 控制器未 escalate
    blocked    ← 闸门未通过，或控制器 escalated（产物不可交付）
    failed     ← 任务本身失败
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .escalation import INFRA_CAUSES, EscalationCause

__all__ = [
    "DeliveryDecision",
    "DeliveryStatus",
    "resolve_delivery_decision",
    "resolve_delivery_status",
]

DeliveryStatus = Literal["delivered", "blocked", "failed"]

#: 控制器裁决中表示"成功判据未满足"的取值
BLOCKING_VERDICTS = frozenset({"escalated"})


@dataclass(frozen=True)
class DeliveryDecision:
    """交付判定结果（含原因分类，便于看板聚合与告警分流）。"""

    status: DeliveryStatus
    reason: str
    cause: str = EscalationCause.NONE.value
    is_infra: bool = False
    needs_attention: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "cause": self.cause,
            "is_infra": self.is_infra,
            "needs_attention": self.needs_attention,
        }


def resolve_delivery_decision(
    *,
    task_succeeded: bool,
    gates_passed: bool,
    verdict: str = "",
    cause: str = "",
) -> DeliveryDecision:
    """D-1：统一判据 —— 闸门 + 控制器裁决 + 原因分类 → 单一交付决策。

    语义优先级（高 → 低）：
      1. 任务失败                  → failed
      2. 闸门未过                  → blocked（原因 gates_failed）
      3. 控制器 escalated          → blocked（按 cause 细分；infra 类单独标记）
      4. 否则                      → delivered
    """
    if not task_succeeded:
        return DeliveryDecision("failed", "task did not succeed")

    if not gates_passed:
        return DeliveryDecision(
            "blocked",
            "delivery gates failed",
            cause="gates_failed",
            needs_attention=True,
        )

    if verdict in BLOCKING_VERDICTS:
        try:
            cause_enum = EscalationCause(cause) if cause else EscalationCause.UNKNOWN
        except ValueError:
            cause_enum = EscalationCause.UNKNOWN
        is_infra = cause_enum in INFRA_CAUSES
        return DeliveryDecision(
            "blocked",
            f"codegen controller verdict=escalated (cause={cause_enum.value})",
            cause=cause_enum.value,
            is_infra=is_infra,
            needs_attention=True,
        )

    return DeliveryDecision("delivered", "")


def resolve_delivery_status(
    *,
    task_succeeded: bool,
    gates_passed: bool,
    verdict: str = "",
) -> tuple[DeliveryStatus, str]:
    """返回 ``(delivery_status, reason)``。

    Args:
        task_succeeded: 任务是否以 SUCCESS 结束。
        gates_passed:   多维校验闸门（语法/逻辑/需求）是否全部通过。
        verdict:        Codegen Controller 裁决（pass/partial/escalated/""）。
    """
    decision = resolve_delivery_decision(
        task_succeeded=task_succeeded, gates_passed=gates_passed, verdict=verdict
    )
    return decision.status, decision.reason
