"""收敛性追踪器 — 监控管道推理步骤是否向目标收敛。

借鉴 ai_council 2 的收敛-发散检测模式，适用于 MoRE OS 的多层管道。
核心机制:
- 追踪每步推理与产出物契约的"距离"
- 检测发散信号（参数来回摆动/输出质量下降/过度完美主义）
- 触发收敛性告警或提前终止

设计原则:
- R9 迭代闭合: 每步推理必须向契约收敛，不允许无限发散
- R16 辅助决策件: 收敛状态是重要的辅助决策信息
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .deliverable import DeliverableContract, KillCriterion, KillSeverity


class ConvergenceState(str, Enum):
    """收敛状态。"""

    CONVERGING = "converging"  # 正在收敛 — 每步都在接近目标
    STABLE = "stable"  # 已稳定 — 输出质量不再提升
    DIVERGING = "diverging"  # 正在发散 — 输出质量下降或偏离
    OSCILLATING = "oscillating"  # 来回摆动 — 在不同方案间反复横跳
    UNKNOWN = "unknown"  # 未知 — 步数不足无法判断


@dataclass
class ConvergenceSnapshot:
    """单步收敛快照。"""

    step: int
    output_hash: str  # 输出的简化哈希（用于检测重复）
    output_length: int  # 输出长度
    completeness: float  # 完整性得分 (0-1, 与契约的匹配度)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "output_hash": self.output_hash,
            "output_length": self.output_length,
            "completeness": round(self.completeness, 3),
        }


@dataclass
class ConvergenceReport:
    """收敛性报告。"""

    state: ConvergenceState = ConvergenceState.UNKNOWN
    snapshots: list[ConvergenceSnapshot] = field(default_factory=list)
    trend: str = ""  # 趋势描述
    divergence_detected: bool = False  # 是否检测到发散
    should_terminate: bool = False  # 是否应提前终止
    killed_by: list[KillCriterion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "trend": self.trend,
            "divergence_detected": self.divergence_detected,
            "should_terminate": self.should_terminate,
            "killed_by": [k.to_dict() for k in self.killed_by],
        }


class ConvergenceTracker:
    """收敛性追踪器 — 在管道每步执行后调用 record() 追踪收敛状态。

    用法:
        tracker = ConvergenceTracker(contract, kill_criteria)
        for each step in pipeline:
            tracker.record(step_number, output_text)
            if tracker.report.should_terminate:
                break  # 提前终止
    """

    # 收敛检测参数
    MIN_STEPS_FOR_DETECTION = 3  # 至少 3 步才开始检测
    DIVERGENCE_COMPLETENESS_DROP = 0.1  # 完整性下降超过 10% 视为发散
    OSCILLATION_THRESHOLD = 2  # 相同输出出现 2 次视为振荡

    def __init__(
        self,
        contract: DeliverableContract | None = None,
        kill_criteria: list[KillCriterion] | None = None,
    ):
        self._contract = contract or DeliverableContract()
        self._kill_criteria = kill_criteria or []
        self._snapshots: list[ConvergenceSnapshot] = []
        self._output_hashes: dict[str, int] = {}  # hash -> count

    def record(
        self, step: int, output: str, completeness: float | None = None
    ) -> ConvergenceReport:
        """记录一步推理并返回当前收敛状态。

        Args:
            step: 当前步数 (从 1 开始)
            output: 当前步的产出文本
            completeness: 预计算的完整性得分；为 None 时内部对 output
                执行一次契约关键词扫描（管道内每层输出不同，无法复用；
                调用方已有结果时应传入以避免重复扫描）。
        """
        # 生成快照
        output_hash = _quick_hash(output)
        if completeness is None:
            completeness = (
                self._compute_completeness(output) if self._contract.dimension_count() > 0 else 0.5
            )

        snapshot = ConvergenceSnapshot(
            step=step,
            output_hash=output_hash,
            output_length=len(output),
            completeness=completeness,
        )
        self._snapshots.append(snapshot)

        # 更新哈希计数
        self._output_hashes[output_hash] = self._output_hashes.get(output_hash, 0) + 1

        # 检测收敛状态
        state = self._detect_state()
        trend = self._compute_trend()
        diverging = state in (ConvergenceState.DIVERGING, ConvergenceState.OSCILLATING)

        # 检查退出条件
        killed = self._check_kill_criteria(output, step)
        should_terminate = diverging or any(
            kc.severity in (KillSeverity.FATAL, KillSeverity.CRITICAL) for kc in killed
        )

        return ConvergenceReport(
            state=state,
            snapshots=list(self._snapshots),
            trend=trend,
            divergence_detected=diverging,
            should_terminate=should_terminate,
            killed_by=killed,
        )

    @staticmethod
    def assess(output: str, contract: DeliverableContract) -> tuple[bool, list[str], float]:
        """Single-scan completeness assessment.

        Returns (complete, missing, completeness_score).  Callers needing
        both the deliverable check and the convergence score should use this
        once and pass the score to :meth:`record` to avoid double scanning.
        """
        complete, missing = contract.check_completeness(output)
        total = contract.dimension_count()
        covered = total - len(
            [
                m
                for m in missing
                if not m.startswith("min_length") and not m.startswith("must_contain")
            ]
        )
        score = covered / total if total > 0 else 0.5
        return complete, missing, score

    def _compute_completeness(self, output: str) -> float:
        """计算输出与契约的完整性匹配度 (0-1)。"""
        if not self._contract.required_dimensions:
            return 0.5
        _complete, missing = self._contract.check_completeness(output)
        total = self._contract.dimension_count()
        covered = total - len(
            [
                m
                for m in missing
                if not m.startswith("min_length") and not m.startswith("must_contain")
            ]
        )
        return covered / total if total > 0 else 0.5

    def _detect_state(self) -> ConvergenceState:
        """检测当前收敛状态。"""
        n = len(self._snapshots)
        if n < self.MIN_STEPS_FOR_DETECTION:
            return ConvergenceState.UNKNOWN

        recent = self._snapshots[-self.MIN_STEPS_FOR_DETECTION :]
        completenesses = [s.completeness for s in recent]

        # 振荡检测: 相同哈希出现多次
        max_repeat = max(self._output_hashes.values(), default=0)
        if max_repeat >= self.OSCILLATION_THRESHOLD:
            return ConvergenceState.OSCILLATING

        # 发散检测: 完整性持续下降
        if n >= 3:
            last3 = completenesses[-3:]
            if (
                len(last3) == 3
                and last3[0] > 0
                and last3[2] < last3[0] - self.DIVERGENCE_COMPLETENESS_DROP
            ):
                return ConvergenceState.DIVERGING

        # 稳定检测: 完整性不再提升
        if n >= 3:
            last3 = completenesses[-3:]
            if max(last3) - min(last3) < 0.05:
                return ConvergenceState.STABLE

        # 收敛检测: 完整性在提升
        if n >= 2 and completenesses[-1] > completenesses[0]:
            return ConvergenceState.CONVERGING

        return ConvergenceState.STABLE

    def _compute_trend(self) -> str:
        """计算趋势描述。"""
        n = len(self._snapshots)
        if n < 2:
            return "步数不足，无法判断趋势"
        first = self._snapshots[0]
        last = self._snapshots[-1]
        if last.completeness > first.completeness + 0.05:
            return "完整性提升中"
        elif last.completeness < first.completeness - 0.05:
            return "完整性下降中"
        else:
            return "完整性基本稳定"

    def _check_kill_criteria(self, output: str, step: int) -> list[KillCriterion]:
        """检查退出条件。"""
        triggered: list[KillCriterion] = []
        output_lower = output.lower()

        for kc in self._kill_criteria:
            trigger = kc.trigger.lower()
            if trigger and trigger in output_lower:
                triggered.append(kc)

        return triggered


def _quick_hash(text: str, length: int = 8) -> str:
    """生成文本的快速哈希（用于重复检测）。"""
    # 取前 500 字符的简化表示
    sample = text[:500].replace(" ", "").replace("\n", "")
    if not sample:
        return "empty"
    # 简单的取模哈希
    h = sum(ord(c) for c in sample) % (10**length)
    return str(h).zfill(length)
