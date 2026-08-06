"""Zero-LLM natural-language → TaskType classifier.

Maps a task query to a :class:`TaskType` using bilingual (en/zh) keyword
scoring, mirroring :mod:`scene_router`'s philosophy: deterministic and
free of LLM cost.  Fallback is :attr:`TaskType.NLP_TASK`.

The classifier is deliberately conservative — a query that matches no
strong signal stays NLP_TASK rather than guessing a code type, so misrouting
a free-text request into the code pipeline is avoided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.types import TaskType

# ASCII keywords are matched as whole words so "prove" does not hit inside
# "improvement"; CJK keywords use plain substring matching.
_ASCII_KEYWORD_RE: dict[str, re.Pattern[str]] = {}

# Keyword → weight. Weights reward strong, type-specific signals over
# generic verbs like "write"/"开发" which appear in many task types.
_KEYWORDS: dict[TaskType, dict[str, float]] = {
    TaskType.CODE_GENERATION: {
        "generate": 3.0,
        "write a function": 3.0,
        "implement": 3.0,
        "代码生成": 3.0,
        "编写": 3.0,
        "生成代码": 3.0,
        "code for": 2.0,
        "script": 2.0,
        "function that": 2.0,
        "app": 2.0,
        "程序": 2.0,
        "开发": 1.5,
        "实现": 1.5,
        "代码": 1.0,
    },
    TaskType.CODE_DEBUGGING: {
        "debug": 3.0,
        "fix the bug": 3.0,
        "报错": 3.0,
        "调试": 3.0,
        "修bug": 3.0,
        "bug": 2.0,
        "traceback": 2.0,
        "exception": 2.0,
        "error": 1.5,
        "修复": 1.5,
        "异常": 1.5,
    },
    TaskType.CODE_REVIEW: {
        "code review": 3.0,
        "review the code": 3.0,
        "审查": 3.0,
        "评审": 3.0,
        "代码审查": 3.0,
    },
    TaskType.CODE_TESTING: {
        "unit test": 3.0,
        "unit tests": 3.0,
        "test the": 2.5,
        "write tests": 3.0,
        "测试用例": 3.0,
        "单元测试": 3.0,
        "编写测试": 3.0,
        "coverage": 2.0,
    },
    TaskType.MATH_REASONING: {
        "prove": 3.0,
        "equation": 2.5,
        "solve for": 2.5,
        "证明": 3.0,
        "数学": 2.5,
        "方程": 2.5,
        "求导": 2.5,
        "计算": 1.5,
        "概率": 2.0,
    },
    TaskType.DATA_ANALYSIS: {
        "analyze": 2.5,
        "analysis": 2.5,
        "statistics": 2.5,
        "报表": 2.5,
        "数据分析": 3.0,
        "统计": 2.5,
        "可视化": 2.0,
        "chart": 2.0,
        "数据": 1.0,
    },
    TaskType.ARCHITECTURE_DESIGN: {
        "architecture": 3.0,
        "system design": 3.0,
        "架构": 3.0,
        "系统设计": 3.0,
        "微服务": 2.5,
        "模块划分": 2.5,
    },
    TaskType.MULTI_AGENT_ORCHESTRATION: {
        "multi-agent": 3.0,
        "orchestration": 3.0,
        "多智能体": 3.0,
        "编排": 3.0,
        "agent协作": 3.0,
    },
    TaskType.SELF_IMPROVEMENT: {
        "self-improve": 3.0,
        "self improvement": 3.0,
        "self-improvement": 3.0,
        "自我改进": 3.0,
        "进化学习": 3.0,
        "自动优化策略": 3.0,
    },
    TaskType.CROSS_DOMAIN_TRANSFER: {
        "transfer learning": 3.0,
        "cross-domain": 3.0,
        "跨域迁移": 3.0,
        "迁移学习": 3.0,
        "迁移": 1.5,
    },
}

# Order matters only for deterministic tie-breaking between equal scores.
_PRIORITY: tuple[TaskType, ...] = (
    TaskType.CODE_DEBUGGING,
    TaskType.CODE_REVIEW,
    TaskType.CODE_TESTING,
    TaskType.CODE_GENERATION,
    TaskType.MATH_REASONING,
    TaskType.DATA_ANALYSIS,
    TaskType.ARCHITECTURE_DESIGN,
    TaskType.MULTI_AGENT_ORCHESTRATION,
    TaskType.SELF_IMPROVEMENT,
    TaskType.CROSS_DOMAIN_TRANSFER,
)

# Confidence scaling, mirroring scene_router: base + reward per hit.
_BASE_CONFIDENCE = 0.6
_HIT_REWARD = 0.12
_MAX_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Classification:
    task_type: TaskType
    confidence: float
    matched_keywords: tuple[str, ...] = ()


def classify_task_type(query: str) -> TaskType:
    """Classify *query* into a concrete :class:`TaskType` (never AUTO)."""
    return classify(query).task_type


def classify(query: str) -> Classification:
    """Return the best classification (with confidence) for *query*.

    Falls back to :attr:`TaskType.NLP_TASK` with confidence 0.5 when no
    keyword reaches the confidence floor.
    """
    lowered = query.lower()

    best_type: TaskType | None = None
    best_score = 0.0
    best_hits: tuple[str, ...] = ()
    for tt in _PRIORITY:
        score = 0.0
        hits: list[str] = []
        for kw, weight in _KEYWORDS[tt].items():
            if _keyword_matches(kw, lowered):
                score += weight
                hits.append(kw)
        if score > best_score:
            best_score = score
            best_type = tt
            best_hits = tuple(hits)

    if best_type is None or best_score < _HIT_REWARD:
        return Classification(TaskType.NLP_TASK, 0.5)

    confidence = min(_MAX_CONFIDENCE, _BASE_CONFIDENCE + _HIT_REWARD * best_score)
    return Classification(best_type, confidence, best_hits)


def _keyword_matches(keyword: str, lowered_query: str) -> bool:
    """Match ASCII keywords as whole words; CJK as substring."""
    if keyword.isascii():
        pattern = _ASCII_KEYWORD_RE.get(keyword)
        if pattern is None:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])")
            _ASCII_KEYWORD_RE[keyword] = pattern
        return pattern.search(lowered_query) is not None
    return keyword in lowered_query
