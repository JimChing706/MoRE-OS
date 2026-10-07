"""Uncertainty Assessor for MoRE v3.0.

Computes a unified uncertainty index U ∈ [0,1] from three dimensions:
1. Semantic complexity — how complex/structure-demanding the query is
2. Historical similarity — how similar to known (solved) tasks
3. Domain boundary — how close to the system's knowledge edges

Low U → "村里人" deterministic mode
High U → "河里人" probabilistic mode (with full pipeline)

Design principle (西尔弗第6个习惯 — 信息价值评估):
    Don't pursue perfect information; pursue +EV information.
    The assessor uses lightweight heuristics, not an extra LLM call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

from ..core.types import TaskType

_log = logging.getLogger(__name__)


# ── Semantic complexity signals ──────────────────────────────────────────
# Keywords that indicate high ambiguity or multi-interpretation potential.

_HIGH_UNCERTAINTY_KEYWORDS: set[str] = {
    # English
    "design",
    "architecture",
    "strategy",
    "innovate",
    "pioneer",
    "novel",
    "unprecedented",
    "creative",
    "ambiguous",
    "speculative",
    "exploratory",
    "hypothesis",
    "theory",
    "unknown",
    "edge case",
    "trade-off",
    "tradeoff",
    "competing",
    "conflicting",
    "paradox",
    # Chinese
    "设计",
    "架构",
    "策略",
    "创新",
    "开创",
    "新颖",
    "前所未有",
    "模糊",
    "推测",
    "探索",
    "假设",
    "理论",
    "未知",
    "边界",
    "权衡",
    "冲突",
    "矛盾",
}

_LOW_UNCERTAINTY_KEYWORDS: set[str] = {
    # English
    "implement",
    "execute",
    "run",
    "fetch",
    "read",
    "write",
    "translate",
    "convert",
    "format",
    "summarize",
    "extract",
    "list",
    "count",
    "calculate",
    "compute",
    "check",
    "hello",
    "hi",
    "simple",
    "basic",
    "quick",
    # Chinese
    "实现",
    "执行",
    "运行",
    "获取",
    "读取",
    "写入",
    "翻译",
    "转换",
    "格式化",
    "摘要",
    "提取",
    "列出",
    "计数",
    "计算",
    "检查",
    "你好",
    "简单",
    "基本",
    "快速",
}

# Task types inherently more uncertain
_HIGH_UNCERTAINTY_TASKS: set[TaskType] = {
    TaskType.ARCHITECTURE_DESIGN,
    TaskType.SELF_IMPROVEMENT,
    TaskType.CROSS_DOMAIN_TRANSFER,
    TaskType.MULTI_AGENT_ORCHESTRATION,
}

_LOW_UNCERTAINTY_TASKS: set[TaskType] = {
    TaskType.NLP_TASK,
    TaskType.DATA_ANALYSIS,
}


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class UncertaintyAssessment:
    """Result of uncertainty evaluation for a task."""

    semantic_complexity: float  # 0-1: lexico-semantic signal
    historical_similarity: float  # 0-1: 1.0 = perfect match, 0.0 = novel
    domain_boundary: float  # 0-1: proximity to knowledge boundary
    aggregated_u: float  # 0-1: weighted composite
    mode: str  # "village" or "river"
    confidence: float  # assessor self-confidence [0,1]
    decomposition: dict[str, Any] = field(default_factory=dict)

    @property
    def is_river(self) -> bool:
        return self.mode == "river"

    @property
    def is_village(self) -> bool:
        return self.mode == "village"


# ── Assessor ─────────────────────────────────────────────────────────────


class UncertaintyAssessor:
    """Lightweight, zero-LLM uncertainty evaluator.

    Computes U from heuristic signals.  Designed to be fast enough
    to run on every request without adding latency.
    """

    # Spectral threshold: U >= THRESHOLD triggers "河里人" mode
    RIVER_THRESHOLD: float = 0.3

    # Weights for the three dimensions (tunable via A/B testing)
    W_SEMANTIC: float = 0.40
    W_HISTORICAL: float = 0.35
    W_DOMAIN: float = 0.25

    def __init__(self, memory: Any | None = None) -> None:
        self._memory = memory
        # Lightweight in-memory cache of historical task embeddings
        self._task_cache: dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def assess(
        self, query: str, task_type: TaskType, context: dict[str, Any] | None = None
    ) -> UncertaintyAssessment:
        """Main entry point: evaluate uncertainty for a task.

        Args:
            query: The task query string
            task_type: TaskType enum value
            context: Optional extra context (prior history, user profile, etc.)

        Returns:
            UncertaintyAssessment with spectral mode decision
        """
        semantic = self._compute_semantic_complexity(query)
        historical = self._compute_historical_similarity(query, task_type)
        domain = self._compute_domain_boundary(task_type, query)

        # Weighted aggregation
        u = (
            self.W_SEMANTIC * semantic
            + self.W_HISTORICAL * (1.0 - historical)  # invert: high similarity → low uncertainty
            + self.W_DOMAIN * domain
        )
        u = max(0.0, min(1.0, u))

        mode = "river" if u >= self.RIVER_THRESHOLD else "village"

        # Assessor confidence in its own judgment
        # Higher when signals are consistent; lower when they conflict
        signal_spread = max(
            abs(semantic - domain),
            abs(semantic - (1.0 - historical)),
            abs(domain - (1.0 - historical)),
        )
        confidence = max(0.3, 1.0 - signal_spread)

        _log.debug(
            "Uncertainty: u=%.3f mode=%s sem=%.2f hist=%.2f dom=%.2f conf=%.2f",
            u,
            mode,
            semantic,
            historical,
            domain,
            confidence,
        )

        return UncertaintyAssessment(
            semantic_complexity=semantic,
            historical_similarity=historical,
            domain_boundary=domain,
            aggregated_u=u,
            mode=mode,
            confidence=confidence,
            decomposition={
                "semantic": semantic,
                "historical": historical,
                "domain": domain,
                "weights": {
                    "semantic": self.W_SEMANTIC,
                    "historical": self.W_HISTORICAL,
                    "domain": self.W_DOMAIN,
                },
            },
        )

    # ── Dimension 1: Semantic Complexity ─────────────────────────────────

    def _compute_semantic_complexity(self, query: str) -> float:
        """Estimate semantic ambiguity/complexity from surface features.

        Returns 0-1 where 1 = highly ambiguous/complex.
        """
        lower = query.lower()
        score = 0.0

        # 1. Query length (longer queries tend to be more complex)
        length = len(query.split())
        if length > 50:
            score += 0.3
        elif length > 20:
            score += 0.2
        elif length > 10:
            score += 0.1

        # 2. High-uncertainty keyword hits
        hi_hits = sum(1 for kw in _HIGH_UNCERTAINTY_KEYWORDS if kw in lower)
        score += min(0.4, hi_hits * 0.15)

        # 3. Low-uncertainty keyword hits (reduce score)
        lo_hits = sum(1 for kw in _LOW_UNCERTAINTY_KEYWORDS if kw in lower)
        score -= min(0.3, lo_hits * 0.1)

        # 4. Question marks and conditionals signal ambiguity
        score += 0.05 * min(5, lower.count("?"))
        if "if" in lower or "如果" in query or "or" in lower.split():
            score += 0.1

        # 5. CJK-aware: Chinese characters per token ≈ 2x English density
        cjk_count = sum(1 for c in query if "\u4e00" <= c <= "\u9fff")
        if cjk_count > 50:
            score += 0.15

        return max(0.0, min(1.0, score))

    # ── Dimension 2: Historical Similarity ───────────────────────────────

    def _compute_historical_similarity(self, query: str, task_type: TaskType) -> float:
        """Estimate how similar this task is to previously solved tasks.

        Returns 0-1 where 1 = highly similar to known tasks.
        For now uses keyword overlap against cached task types.
        In Phase 3 this will query the Risk Decision Knowledge Graph.
        """
        # Base similarity from task type
        if task_type in _HIGH_UNCERTAINTY_TASKS:
            base = 0.4
        elif task_type in _LOW_UNCERTAINTY_TASKS:
            base = 0.8
        else:
            base = 0.6

        # Try memory lookup if available
        if self._memory and hasattr(self._memory, "search"):
            try:
                results = self._memory.search(query, top_k=3)
                if results:
                    # Average similarity to top results
                    sim = sum(r.get("score", 0.5) for r in results) / len(results)
                    return cast(float, max(0.2, min(0.95, sim)))
            except Exception as exc:  # noqa: BLE001
                _log.warning("Memory search failed for uncertainty assessment: %s", exc)

        # Fallback: adjust base by keyword signals
        lower = query.lower()
        known_patterns = sum(1 for kw in _LOW_UNCERTAINTY_KEYWORDS if kw in lower)
        unknown_patterns = sum(1 for kw in _HIGH_UNCERTAINTY_KEYWORDS if kw in lower)

        adjusted = base + (known_patterns * 0.05) - (unknown_patterns * 0.08)
        return max(0.1, min(0.95, adjusted))

    # ── Dimension 3: Domain Boundary ─────────────────────────────────────

    def _compute_domain_boundary(self, task_type: TaskType, query: str) -> float:
        """Estimate how close the task is to the system's knowledge boundary.

        Returns 0-1 where 1 = at/beyond boundary (high domain uncertainty).
        """
        # Task types near the boundary
        if task_type in _HIGH_UNCERTAINTY_TASKS:
            base = 0.7
        elif task_type == TaskType.PLUGIN_DEFINED:
            base = 0.9  # Plugin tasks are by definition at the boundary
        elif task_type in _LOW_UNCERTAINTY_TASKS:
            base = 0.15
        else:
            base = 0.4

        # Domain-crossing keywords push toward boundary
        lower = query.lower()
        boundary_signals = [
            "multi-",
            "cross-",
            "transfer",
            "generalize",
            "adapt",
            "跨",
            "迁移",
            "泛化",
            "通用",
            "跨域",
        ]
        hits = sum(1 for s in boundary_signals if s in lower)
        base += hits * 0.15

        return max(0.0, min(1.0, base))

    # ── Utility ──────────────────────────────────────────────────────────

    def set_river_threshold(self, threshold: float) -> None:
        """Update the spectral threshold (for A/B testing)."""
        self.RIVER_THRESHOLD = max(0.1, min(0.9, threshold))
        _log.info("RIVER_THRESHOLD updated to %.2f", self.RIVER_THRESHOLD)

    def set_weights(self, semantic: float, historical: float, domain: float) -> None:
        """Update dimension weights (for A/B testing)."""
        total = semantic + historical + domain
        self.W_SEMANTIC = semantic / total
        self.W_HISTORICAL = historical / total
        self.W_DOMAIN = domain / total
        _log.info(
            "Weights updated: sem=%.2f hist=%.2f dom=%.2f",
            self.W_SEMANTIC,
            self.W_HISTORICAL,
            self.W_DOMAIN,
        )
