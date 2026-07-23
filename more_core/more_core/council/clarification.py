"""需求澄清预处理 — 借鉴 ai_council clarification.py 的 T00 模式。

在任务执行前，对模糊需求进行澄清预处理:
- 识别模糊/缺失信息
- 生成澄清问题（根据场景深度决定问题数量）
- 列出系统假设
- 提供用户反馈回路

设计原则:
- 澄清预处理是可选的（不影响 fast path）
- 仅在场景分类置信度低或深度模式时触发
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClarificationResult:
    """需求澄清结果。"""

    clarifying_questions: list[dict[str, Any]] = field(default_factory=list)
    # [{"question": str, "category": str, "importance": "critical"|"important"|"nice_to_have"}]
    assumptions: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    rationale: str = ""
    mode: str = "standard"

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarifying_questions": self.clarifying_questions,
            "assumptions": self.assumptions,
            "needs_clarification": self.needs_clarification,
            "rationale": self.rationale,
            "mode": self.mode,
        }


# 澄清提示词模板（供 LLM 使用）
CLARIFICATION_PROMPT = """你是需求澄清助手，负责在执行任务前识别模糊信息。

规则:
1. 分析用户的问题，找出所有模糊、缺失、可能影响结果的信息
2. 根据当前模式决定问题数量
3. 每个问题附带 category 和 importance 分类
4. 最后列出系统必须做的假设

当前模式: {mode}
用户问题: {question}
深度提示: {hint}

输出必须是严格 JSON 格式:
{{
  "clarifying_questions": [
    {{"question": "你预期的目标是什么?", "category": "scope", "importance": "critical"}}
  ],
  "rationale": "选择这些问题的理由",
  "assumptions": ["如果用户未明确，系统将假设为标准场景"],
  "needs_clarification": true/false
}}

禁止输出 JSON 之外的任何内容。
"""


def build_clarification_prompt(question: str, mode: str = "standard") -> str:
    """构建澄清提示词。"""
    depth_hints = {
        "quick": "只问 1 个最关键的问题。假设用户需要快速决策。",
        "standard": "问 1-2 个问题，覆盖范围和约束。",
        "deep": "问 2-3 个问题，覆盖范围、约束、预期结果和边界条件。",
    }
    hint = depth_hints.get(mode, depth_hints["standard"])
    return CLARIFICATION_PROMPT.format(question=question, mode=mode, hint=hint)


def parse_clarification_response(response: dict[str, Any]) -> ClarificationResult:
    """解析 LLM 澄清响应。"""
    return ClarificationResult(
        clarifying_questions=list(response.get("clarifying_questions", [])),
        assumptions=list(response.get("assumptions", [])),
        needs_clarification=bool(response.get("needs_clarification", False)),
        rationale=str(response.get("rationale", "")),
        mode=str(response.get("mode", "standard")),
    )
