"""升级原因分类 —— 统一"闸门判据"与"控制器判据"的语义。

背景（评估报告 D-1 / R-20）：
交付闸门（语法/逻辑/需求）与 Codegen Controller 是两套独立判据，
历史上会出现「闸门通过但 Controller 判 escalated」的口径冲突；
而且 escalated 只记录"沙箱失败 3/3 轮"，无法区分：

    * 代码**真的跑不通**（真阴性，必须拦）
    * 沙箱**超时**（可能是环境慢，需调参/告警）
    * 沙箱**不可用**（工具未注册/环境故障，属基础设施问题）

本模块把这些原因收敛成枚举 + 处置语义，供控制器、交付策略与看板共用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "BLOCKING_CAUSES",
    "INFRA_CAUSES",
    "EscalationCause",
    "EscalationInfo",
    "classify_escalation",
]


class EscalationCause(str, Enum):
    """升级（escalated）的根因分类。"""

    NONE = "none"
    CODE_ERROR = "code_error"  # 沙箱执行了，但代码报错
    ASSERTIONS_FAILED = "assertions_failed"  # 验收断言未通过
    SANDBOX_TIMEOUT = "sandbox_timeout"  # 沙箱超时
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"  # 沙箱/工具不可用（基础设施）
    SAFETY_BLOCKED = "safety_blocked"  # 静态安全检查拦截
    REVIEW_REJECTED = "review_rejected"  # 评审面板 P1/P2 否决
    STAGNANT = "stagnant"  # 修复轮次耗尽且无进展
    UNKNOWN = "unknown"


#: 必须阻断交付的原因（产物不可信）
BLOCKING_CAUSES: frozenset[EscalationCause] = frozenset(
    {
        EscalationCause.CODE_ERROR,
        EscalationCause.ASSERTIONS_FAILED,
        EscalationCause.SANDBOX_TIMEOUT,
        EscalationCause.SANDBOX_UNAVAILABLE,
        EscalationCause.SAFETY_BLOCKED,
        EscalationCause.REVIEW_REJECTED,
        EscalationCause.STAGNANT,
        EscalationCause.UNKNOWN,
    }
)

#: 基础设施类原因（与"代码质量"无关，应对运维告警而非归咎于模型）
INFRA_CAUSES: frozenset[EscalationCause] = frozenset(
    {EscalationCause.SANDBOX_UNAVAILABLE, EscalationCause.SANDBOX_TIMEOUT}
)

#: 沙箱"不可用"的典型特征串（工具未注册 / 环境异常）
_UNAVAILABLE_HINTS = (
    "unknown tool",
    "not found",
    "no such file",
    "permission denied",
    "not registered",
    "unavailable",
)
_TIMEOUT_HINTS = ("timeout", "timed out", "timed_out")


@dataclass(frozen=True)
class EscalationInfo:
    """分类结果 + 处置语义。"""

    cause: EscalationCause
    detail: str = ""
    is_blocking: bool = True
    is_infra: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause": self.cause.value,
            "detail": self.detail[:400],
            "is_blocking": self.is_blocking,
            "is_infra": self.is_infra,
        }


def classify_escalation(
    *,
    decision: str,
    checks: dict[str, Any] | None,
    artifacts: dict[str, Any] | None = None,
) -> EscalationInfo:
    """把一次 Controller 裁决归类为可诊断的原因。

    Args:
        decision:  Controller 决策（pass / partial / escalated）。
        checks:    控制器判据布尔集（sandbox / assertions / review / blocked …）。
        artifacts: 控制器保留的现场（last_error / timed_out / violations …）。
    """
    checks = checks or {}
    artifacts = artifacts or {}
    last_error = str(artifacts.get("last_error") or "")
    timed_out = bool(artifacts.get("timed_out"))

    if decision != "escalated":
        info = EscalationInfo(EscalationCause.NONE, "", is_blocking=False, is_infra=False)
        return info

    if checks.get("blocked") or artifacts.get("violations"):
        return EscalationInfo(EscalationCause.SAFETY_BLOCKED, last_error)

    if checks.get("review") == "rejected":
        return EscalationInfo(EscalationCause.REVIEW_REJECTED, last_error)

    if checks.get("sandbox") is False:
        if timed_out or any(h in last_error.lower() for h in _TIMEOUT_HINTS):
            # 超时可能是"代码死循环"也可能是"环境慢"，先按基础设施告警，
            # 由 last_error/last_output_tail 进一步人工判定。
            return EscalationInfo(EscalationCause.SANDBOX_TIMEOUT, last_error, is_infra=True)
        if any(h in last_error.lower() for h in _UNAVAILABLE_HINTS):
            return EscalationInfo(EscalationCause.SANDBOX_UNAVAILABLE, last_error, is_infra=True)
        if last_error:
            # 沙箱确实跑了并报错 → 代码问题
            return EscalationInfo(EscalationCause.CODE_ERROR, last_error)
        return EscalationInfo(EscalationCause.UNKNOWN, "sandbox failed without a recorded reason")

    if checks.get("assertions") is False and checks.get("stagnant"):
        return EscalationInfo(EscalationCause.ASSERTIONS_FAILED, last_error)

    if checks.get("assertions") is False:
        return EscalationInfo(EscalationCause.ASSERTIONS_FAILED, last_error)

    if checks.get("stagnant"):
        return EscalationInfo(EscalationCause.STAGNANT, last_error)

    return EscalationInfo(EscalationCause.UNKNOWN, last_error)
