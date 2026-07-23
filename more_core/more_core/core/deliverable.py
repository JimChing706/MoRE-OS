"""产出物契约与业务预期管理 — 借鉴 ai_council 2 的 T14 七维结论 + Kill Criteria。

为 MoRE OS 的任务管道引入:
- DeliverableContract: 定义"完成"的标准（格式/质量/维度）
- TaskExpectation: 业务层面的预期管理（目标/交付物/Kill Criteria）
- KillCriterion: 明确的退出条件（防止 AI 无边界发散）

设计原则:
- R2 诚实铁律: 每个产出物必须可度量其完成度
- R14 多维结论完整性: 契约强制多维输出结构
- R9 迭代闭合: 每步推理必须向契约收敛
- 收敛性约束: 发散超过阈值 → 提前终止
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeliverableKind(str, Enum):
    """产出物类型 — 定义任务完成后应交付什么。"""

    CODE = "code"  # 代码产出
    ARCHITECTURE = "architecture"  # 架构设计文档
    ANALYSIS = "analysis"  # 分析报告
    DECISION = "decision"  # 决策建议
    PLAN = "plan"  # 执行计划
    EXPLANATION = "explanation"  # 解释说明
    CREATIVE = "creative"  # 创意产出
    CUSTOM = "custom"  # 自定义


class KillSeverity(str, Enum):
    """退出条件的严重级别。"""

    FATAL = "fatal"  # 致命 — 触发后必须立即终止
    CRITICAL = "critical"  # 关键 — 触发后应尽快终止
    WARNING = "warning"  # 警告 — 触发后记录但不终止


@dataclass
class KillCriterion:
    """退出条件 — 定义在什么情况下任务应该被放弃或根本性改变方向。

    借鉴 ai_council 2 chair_self_check 的 Kill Criteria。
    """

    condition: str  # 可衡量的触发条件描述
    severity: KillSeverity = KillSeverity.WARNING
    timeline: str = ""  # 在什么时间点检查
    trigger: str = ""  # 具体触发条件
    fallback: str = ""  # 触发后的备选方案

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "severity": self.severity.value,
            "timeline": self.timeline,
            "trigger": self.trigger,
            "fallback": self.fallback,
        }


@dataclass
class DeliverableContract:
    """产出物契约 — 定义任务"完成"的标准。

    借鉴 ai_council 2 的 T14 七维结论框架，适配 MoRE OS 的任务管道。
    契约作为管道执行的收敛目标，每一层推理都应向契约定义的维度收敛。

    核心维度:
    - kind: 产出物类型
    - required_dimensions: 必须包含的维度（如 code 需要 correctness + tests）
    - quality_gates: 质量门禁（如 min_length, must_contain）
    - acceptance_criteria: 验收标准（如 "所有测试通过"）
    """

    kind: DeliverableKind = DeliverableKind.CUSTOM
    required_dimensions: list[str] = field(default_factory=list)
    # 如 ["core_output", "reasoning", "risks", "alternatives"]
    quality_gates: dict[str, Any] = field(default_factory=dict)
    # 如 {"min_length": 100, "must_contain": ["方案", "风险"]}
    acceptance_criteria: list[str] = field(default_factory=list)
    # 如 ["所有API端点有测试覆盖", "文档包含回滚方案"]
    description: str = ""

    def dimension_count(self) -> int:
        """必须覆盖的维度数。"""
        return len(self.required_dimensions)

    def check_completeness(self, output: str) -> tuple[bool, list[str]]:
        """检查产出物是否满足契约的完整性要求。

        Returns:
            (是否完整, 缺失维度列表)
        """
        missing: list[str] = []
        output_lower = output.lower()

        for dim in self.required_dimensions:
            # 启发式检查: 维度关键词是否在输出中出现
            dim_keywords = {
                "core_output": ["核心结论", "方案", "输出", "结果", "conclusion"],
                "reasoning": ["推理", "分析", "原因", "依据", "reasoning", "因为"],
                "risks": ["风险", "risk", "隐患", "威胁"],
                "alternatives": ["替代", "备选", "方案二", "alternative", "另一种"],
                "action_items": ["行动", "步骤", "下一步", "action", "todo", "计划"],
                "tests": ["测试", "test", "用例", "验证"],
                "performance": ["性能", "延迟", "吞吐", "performance", "latency"],
                "security": ["安全", "认证", "授权", "security", "auth"],
            }
            keywords = dim_keywords.get(dim, [dim])
            if not any(kw.lower() in output_lower for kw in keywords):
                missing.append(dim)

        # 质量门禁检查
        for gate, value in self.quality_gates.items():
            if gate == "min_length":
                if len(output) < int(value):
                    missing.append(f"min_length({value})")
            elif gate == "must_contain":
                for keyword in value if isinstance(value, list) else [value]:
                    if keyword.lower() not in output_lower:
                        missing.append(f"must_contain:{keyword}")

        return len(missing) == 0, missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "required_dimensions": self.required_dimensions,
            "quality_gates": self.quality_gates,
            "acceptance_criteria": self.acceptance_criteria,
            "description": self.description,
        }

    # ── 工厂方法: 预定义契约模板 ──────────────────────────────────

    @classmethod
    def for_code_generation(cls) -> "DeliverableContract":
        """代码生成任务的标准契约。"""
        return cls(
            kind=DeliverableKind.CODE,
            required_dimensions=["core_output", "reasoning", "tests"],
            quality_gates={"min_length": 50, "must_contain": ["```"]},
            acceptance_criteria=["代码可运行", "包含测试用例", "有错误处理"],
            description="代码生成任务: 交付可运行代码 + 测试 + 说明",
        )

    @classmethod
    def for_architecture_design(cls) -> "DeliverableContract":
        """架构设计任务的标准契约。"""
        return cls(
            kind=DeliverableKind.ARCHITECTURE,
            required_dimensions=["core_output", "reasoning", "risks", "alternatives"],
            quality_gates={"min_length": 200, "must_contain": ["模块", "接口"]},
            acceptance_criteria=["有架构图或文字描述", "说明了关键决策的权衡", "包含风险分析"],
            description="架构设计任务: 交付架构方案 + 决策理由 + 风险评估",
        )

    @classmethod
    def for_analysis(cls) -> "DeliverableContract":
        """分析任务的标准契约。"""
        return cls(
            kind=DeliverableKind.ANALYSIS,
            required_dimensions=["core_output", "reasoning", "risks"],
            quality_gates={"min_length": 100},
            acceptance_criteria=["有数据支撑的结论", "说明了分析方法的局限性"],
            description="分析任务: 交付分析报告 + 推理链 + 风险标注",
        )

    @classmethod
    def for_decision(cls) -> "DeliverableContract":
        """决策建议任务的标准契约。"""
        return cls(
            kind=DeliverableKind.DECISION,
            required_dimensions=[
                "core_output",
                "reasoning",
                "alternatives",
                "risks",
                "action_items",
            ],
            quality_gates={"min_length": 150},
            acceptance_criteria=["有明确的决策建议", "列出了替代方案", "有风险评估"],
            description="决策建议任务: 交付明确建议 + 替代方案 + 风险矩阵",
        )


@dataclass
class TaskExpectation:
    """任务业务预期 — 在执行前定义成功标准和退出条件。

    集成到 TaskRequest 中，供管道在执行过程中参考:
    - contract: 产出物契约（定义"完成"的样子）
    - kill_criteria: 退出条件（定义"何时放弃"）
    - target_confidence: 目标置信度（低于此值触发警告）
    - max_iterations: 最大推理步数（防止无限循环）
    """

    contract: DeliverableContract = field(default_factory=DeliverableContract)
    kill_criteria: list[KillCriterion] = field(default_factory=list)
    target_confidence: float = 60.0  # 目标置信度分数 (0-100)
    max_iterations: int = 10  # 最大推理步数
    timeout_s: float = 60.0  # 超时时间

    def check_kill_criteria(self, output: str, step_count: int) -> list[KillCriterion]:
        """检查是否触发了退出条件。

        Returns:
            被触发的 KillCriterion 列表（空列表 = 未触发）
        """
        triggered: list[KillCriterion] = []

        for kc in self.kill_criteria:
            # 简化的启发式检查: 看触发条件关键词是否在输出中出现
            trigger = kc.trigger.lower()
            if trigger and trigger in output.lower():
                triggered.append(kc)

        # 步数超限检查
        if step_count >= self.max_iterations:
            triggered.append(
                KillCriterion(
                    condition=f"推理步数超过上限 ({step_count} >= {self.max_iterations})",
                    severity=KillSeverity.FATAL,
                    fallback="使用当前最优中间结果作为输出",
                )
            )

        return triggered

    def is_blocking(self, triggered: list[KillCriterion]) -> bool:
        """是否有致命/关键的退出条件被触发。"""
        return any(kc.severity in (KillSeverity.FATAL, KillSeverity.CRITICAL) for kc in triggered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.to_dict(),
            "kill_criteria": [kc.to_dict() for kc in self.kill_criteria],
            "target_confidence": self.target_confidence,
            "max_iterations": self.max_iterations,
            "timeout_s": self.timeout_s,
        }

    @classmethod
    def default_for(cls, kind: DeliverableKind) -> "TaskExpectation":
        """为指定产出物类型创建默认预期。"""
        contract_map = {
            DeliverableKind.CODE: DeliverableContract.for_code_generation,
            DeliverableKind.ARCHITECTURE: DeliverableContract.for_architecture_design,
            DeliverableKind.ANALYSIS: DeliverableContract.for_analysis,
            DeliverableKind.DECISION: DeliverableContract.for_decision,
        }
        factory = contract_map.get(kind, DeliverableContract)
        return cls(
            contract=factory(),
            kill_criteria=[
                KillCriterion(
                    condition="如果在预定时间内无法产出有效结果",
                    severity=KillSeverity.WARNING,
                    timeline="首个推理步骤完成后",
                    trigger="无法完成",
                    fallback="返回当前最佳中间结果",
                ),
            ],
        )
