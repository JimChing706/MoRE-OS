"""增强置信度模型 — 借鉴 ai_council confidence.py 的 4 维置信度设计。

将 more_core 的简单 confidence float (默认 0.8) 升级为可审计的多维度模型:
- evidence_strength: 证据强度（引用了多少具体数据/推理链）
- opinion_consistency: 观点一致性（多角色/多层次结论是否一致）
- domain_familiarity: 领域熟悉度（对任务领域的覆盖程度）
- temporal_stability: 时间稳定性（结论对变化的敏感度）

设计原则:
- 聚合、校验、分级由确定性代码执行（可复算、可审计）
- LLM 评分 + 代码聚合 = 审计链路完整
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DIMENSIONS: tuple[str, ...] = (
    "evidence_strength",
    "opinion_consistency",
    "domain_familiarity",
    "temporal_stability",
)

MAX_PER_DIMENSION = 25.0

# 分级建议 (下界, 等级, 建议)
GRADE_BANDS: tuple[tuple[float, str, str], ...] = (
    (80.0, "high", "高置信度: 可直接行动"),
    (60.0, "medium", "中等置信度: 建议先验证关键假设"),
    (40.0, "low", "低置信度: 需要更多信息"),
    (0.0, "very_low", "极低置信度: 不建议基于当前信息决策"),
)


class ConfidenceError(ValueError):
    """置信度计算违规: 无依据/越界/缺维度。"""


@dataclass
class ConfidenceBreakdown:
    """4 维置信度分解结果。"""

    evidence_strength: float = 0.0
    opinion_consistency: float = 0.0
    domain_familiarity: float = 0.0
    temporal_stability: float = 0.0
    total: float = 0.0
    level: str = "very_low"
    advice: str = ""
    rationale: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": {
                "evidence_strength": self.evidence_strength,
                "opinion_consistency": self.opinion_consistency,
                "domain_familiarity": self.domain_familiarity,
                "temporal_stability": self.temporal_stability,
            },
            "total": self.total,
            "level": self.level,
            "advice": self.advice,
            "rationale": self.rationale,
        }


def compute_breakdown(
    scores: dict[str, float],
    rationale: dict[str, str],
) -> ConfidenceBreakdown:
    """由 4 维得分 + 依据 → 完整置信度分解。

    规则:
    1. 4 维必须齐全，缺一报错
    2. 每维 0-25，越界报错
    3. 每维必须有依据（rationale），空依据报错
    4. 总分 = 4 维得分之和
    5. 分级由 GRADE_BANDS 查表确定
    """
    _validate_scores(scores, rationale)

    total = round(sum(float(scores[d]) for d in DIMENSIONS), 2)
    level, advice = _grade(total)

    return ConfidenceBreakdown(
        evidence_strength=float(scores["evidence_strength"]),
        opinion_consistency=float(scores["opinion_consistency"]),
        domain_familiarity=float(scores["domain_familiarity"]),
        temporal_stability=float(scores["temporal_stability"]),
        total=total,
        level=level,
        advice=advice,
        rationale={d: str(rationale[d]).strip() for d in DIMENSIONS},
    )


def compute_simple_breakdown(
    layer_confidence: float = 0.8,
    num_layers: int = 1,
    has_evidence: bool = False,
) -> ConfidenceBreakdown:
    """从简单参数推断置信度分解（无需 LLM 评分）。

    用于 LayerResult.confidence 的向后兼容升级。
    """
    # 证据强度: 有明确推理链时给分
    ev = min(25.0, 15.0 if has_evidence else 5.0)
    # 观点一致性: 多层次管道中越少冲突给分越高
    oc = min(25.0, 20.0 if num_layers <= 2 else 15.0)
    # 领域熟悉度: 基于 layer_confidence 推断
    df = min(25.0, layer_confidence * 25.0)
    # 时间稳定性: 默认中等
    ts = 15.0

    scores = {
        "evidence_strength": ev,
        "opinion_consistency": oc,
        "domain_familiarity": df,
        "temporal_stability": ts,
    }
    rationale = {
        "evidence_strength": "启发式推断: 基于是否有明确推理链",
        "opinion_consistency": f"启发式推断: 基于 {num_layers} 层管道",
        "domain_familiarity": f"启发式推断: 基于层置信度 {layer_confidence}",
        "temporal_stability": "启发式推断: 默认中等稳定性",
    }

    return compute_breakdown(scores, rationale)


# ── 内部辅助 ────────────────────────────────────────────────────────


def _validate_scores(scores: dict[str, float], rationale: dict[str, str]) -> None:
    """校验得分和依据。不合法时抛 ConfidenceError。"""
    missing = [d for d in DIMENSIONS if d not in scores]
    if missing:
        raise ConfidenceError(f"缺少评分维度: {missing}，4 维缺一不可")

    extra = [d for d in scores if d not in DIMENSIONS]
    if extra:
        raise ConfidenceError(f"未定义的评分维度: {extra}")

    for dim in DIMENSIONS:
        value = scores[dim]
        if not isinstance(value, (int, float)) or not 0 <= value <= MAX_PER_DIMENSION:
            raise ConfidenceError(
                f"维度 '{dim}' 得分 {value!r} 越界(合法范围 0-{MAX_PER_DIMENSION:g})"
            )
        reason = rationale.get(dim)
        if not reason or not str(reason).strip():
            raise ConfidenceError(f"维度 '{dim}' 缺少评分依据(rationale) — 禁止无据数字")


def _grade(total: float) -> tuple[str, str]:
    """总分 → (等级, 行动建议)。"""
    if not 0 <= total <= 100:
        raise ConfidenceError(f"总分 {total!r} 越界(合法范围 0-100)")
    for lower_bound, level, advice in GRADE_BANDS:
        if total >= lower_bound:
            return level, advice
    # Should be unreachable
    return "very_low", "极低置信度: 不建议基于当前信息决策"


# 供 LLM 评分的细则模板
SCORING_RUBRIC = """请对以下 4 个维度分别打分(0-25 的整数)并给出一句话依据:

1. evidence_strength 证据强度:
   - 推理链是否引用了具体数据/代码/文档？依据是否可追溯？
2. opinion_consistency 观点一致性:
   - 多个推理步骤/角色结论是否一致？分歧的性质是什么？
3. domain_familiarity 领域熟悉度:
   - 对任务领域的知识覆盖程度如何？是否存在明显盲区？
4. temporal_stability 时间稳定性:
   - 结论对近期变化的敏感度？关键假设短期内可能改变吗？

输出 JSON: {"scores": {维度: 整数分数}, "rationale": {维度: "一句话依据"}}
总分将由系统自动计算，你不需要输出总分。
"""
