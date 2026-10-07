"""Meta-Orchestrator — Risk-Aware Spectral Router for MoRE v3.0.

Implements the "村里人/河里人" (Village/River) spectral switching pattern:
- Low uncertainty (U < 0.3) → "village" deterministic mode
- High uncertainty (U ≥ 0.3) → "river" probabilistic mode

This is the core architectural upgrade from v2.0 static routing
to v3.0 context-aware risk-philosophy switching.

Design principles (西尔弗习惯工程化):
  #5 止损纪律 — budget limits strictly enforced per mode
  #7 多样化下注 — river mode diversifies across experts
  #11 网络效应 — collaborative routing when U is high
  #13 退出策略 — early exit for village mode tasks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.types import LayerId, TaskType
from .uncertainty import UncertaintyAssessment, UncertaintyAssessor

_log = logging.getLogger(__name__)


# ── Routing mode ─────────────────────────────────────────────────────────


class RoutingMode(Enum):
    VILLAGE = "village"  # Deterministic, single-expert, fast path
    RIVER = "river"  # Probabilistic, multi-expert, full pipeline


# ── Mode-specific pipeline configs ──────────────────────────────────────

_VILLAGE_PIPELINE: list[LayerId] = [LayerId.L4, LayerId.L1, LayerId.L0]
_RIVER_PIPELINE: list[LayerId] = [LayerId.L4, LayerId.L3, LayerId.L1, LayerId.L0]

# For high-complexity river tasks, add L5 metacognition + L2 evolution.
# L2 自带双重门控（settings.enable_evolution && request.allow_self_improvement），
# 门控关闭时只返回 evolved=False 的 no-op 步骤，因此纳入管道是安全的；
# 此前谱管道完全不含 L2，导致"MORE_ENABLE_EVOLUTION + SELF_IMPROVEMENT→L2"契约失效。
_RIVER_DEEP_PIPELINE: list[LayerId] = [
    LayerId.L5,
    LayerId.L2,
    LayerId.L4,
    LayerId.L3,
    LayerId.L1,
    LayerId.L0,
]


@dataclass(slots=True)
class MetaRoutingDecision:
    """Output of Meta-Orchestrator route decision."""

    pipeline: list[LayerId]
    mode: str  # "village" or "river"
    uncertainty_assessment: UncertaintyAssessment
    reasoning: str  # Human-readable explanation
    guardrail_hints: dict[str, Any]  # Hints for DynamicGuardrails
    resource_budget: dict[str, Any]  # Token/time/cost budget per mode

    @property
    def is_river(self) -> bool:
        return self.mode == "river"

    @property
    def is_village(self) -> bool:
        return self.mode == "village"


# ── Meta-Orchestrator ────────────────────────────────────────────────────


class MetaOrchestrator:
    """Top-level risk-aware router.

    Usage::

        meta = MetaOrchestrator(layer_router, memory=core.memory)
        decision = meta.route(request)
        # decision.pipeline → [L4, L1, L0] for simple tasks
        # decision.pipeline → [L5, L4, L3, L1, L0] for complex tasks
    """

    def __init__(self, layer_router: Any | None = None, memory: Any | None = None) -> None:
        self._layer_router = layer_router
        self._assessor = UncertaintyAssessor(memory=memory)
        self._mode_stats: dict[str, int] = {"village": 0, "river": 0}

    @property
    def assessor(self) -> UncertaintyAssessor:
        return self._assessor

    # ── Main routing entry point ─────────────────────────────────────────

    def route(
        self,
        task_type: TaskType,
        query: str,
        *,
        context: dict[str, Any] | None = None,
        require_metacognitive: bool = False,
    ) -> MetaRoutingDecision:
        """Route a task through the spectral decision engine.

        Args:
            task_type: Category of the task
            query: The user query
            context: Optional additional context
            require_metacognitive: Force L5 metacognition regardless of mode

        Returns:
            MetaRoutingDecision with pipeline, mode, and guardrail hints
        """
        # 1. Assess uncertainty
        assessment = self._assessor.assess(query, task_type, context)

        # 2. Determine spectral mode
        mode = RoutingMode.RIVER if assessment.is_river else RoutingMode.VILLAGE
        self._mode_stats[mode.value] += 1

        # 3. Build pipeline per mode
        if mode == RoutingMode.VILLAGE:
            pipeline = list(_VILLAGE_PIPELINE)
            reasoning = (
                f"村里人模式 (U={assessment.aggregated_u:.2f}<0.3): "
                f"确定性快速路径, 单Expert, 轻量验证"
            )
        else:
            # River mode — full pipeline with optional metacognition
            needs_deep = assessment.aggregated_u >= 0.7 or require_metacognitive
            pipeline = list(_RIVER_DEEP_PIPELINE if needs_deep else _RIVER_PIPELINE)
            reasoning = (
                f"河里人模式 (U={assessment.aggregated_u:.2f}≥0.3): "
                f"概率化路由, 多Expert协作, 深度验证"
                f"{', MetaCognition' if needs_deep else ''}"
            )

        # 4. Generate guardrail hints based on mode + U
        guardrail_hints = self._build_guardrail_hints(assessment, mode)

        # 5. Resource budget per mode
        resource_budget = self._build_resource_budget(assessment, mode)

        _log.info(
            "MetaRoute: mode=%s U=%.2f pipeline=%s reasoning=%s",
            mode.value,
            assessment.aggregated_u,
            [lid.value for lid in pipeline],
            reasoning,
        )

        return MetaRoutingDecision(
            pipeline=pipeline,
            mode=mode.value,
            uncertainty_assessment=assessment,
            reasoning=reasoning,
            guardrail_hints=guardrail_hints,
            resource_budget=resource_budget,
        )

    # ── Pipeline helpers ──────────────────────────────────────────────────

    def _build_guardrail_hints(
        self, assessment: UncertaintyAssessment, mode: RoutingMode
    ) -> dict[str, Any]:
        """Generate DynamicGuardrails hints based on mode and U."""
        if mode == RoutingMode.VILLAGE:
            return {
                "token_budget": 1024,
                "timeout_s": 30,
                "validation_layers": 1,
                "sandbox_level": "light",
                "cross_validation_required": False,
                "human_in_the_loop": False,
                "max_experts": 1,
            }
        else:
            u = assessment.aggregated_u
            deep = u >= 0.7
            return {
                "token_budget": 4096 if not deep else 8192,
                "timeout_s": 60 if not deep else 120,
                "validation_layers": 2 if not deep else 4,
                "sandbox_level": "standard" if not deep else "strict",
                "cross_validation_required": deep,
                "human_in_the_loop": u > 0.8,
                "max_experts": 2 if not deep else 3,
            }

    def _build_resource_budget(
        self, assessment: UncertaintyAssessment, mode: RoutingMode
    ) -> dict[str, Any]:
        """Allocate resource budget based on mode.

        Village mode: tight budget, fast response expected.
        River mode: proportional budget to uncertainty.
        """
        if mode == RoutingMode.VILLAGE:
            return {
                "max_tokens": 2048,
                "max_time_s": 30.0,
                "max_cost_usd": 0.001,
                "parallel_calls": 1,
            }
        else:
            u = assessment.aggregated_u
            return {
                "max_tokens": int(4096 + u * 8192),
                "max_time_s": 60.0 + u * 60.0,
                "max_cost_usd": 0.003 + u * 0.01,
                "parallel_calls": 2 + int(u * 3),
            }

    # ── Statistics / introspection ────────────────────────────────────────

    def get_mode_stats(self) -> dict[str, int]:
        """Return village/river routing counts."""
        return dict(self._mode_stats)

    # ── Personality-aware Expert selection ───────────────────────────────

    def select_expert(
        self,
        task_type: TaskType,
        candidates: list[dict[str, Any]],
        *,
        user_risk_preference: float | None = None,
    ) -> dict[str, Any] | None:
        """Select best Expert considering both capability AND personality.

        Routing formula (v3.0 双模态):
            score = α·capability + β·personality_match + γ·risk_alignment

        Where:
            α = 0.5 (task capability)
            β = 0.3 (personality-query fit)
            γ = 0.2 (risk appetite alignment with task uncertainty)

        Args:
            task_type: Category of task
            candidates: List of Expert dicts with 'capability' and optional 'soul_profile'
            user_risk_preference: User's risk appetite (0=conservative, 1=aggressive)

        Returns:
            Best candidate dict or None if no candidates
        """
        from .soul_profile import SoulProfile

        if not candidates:
            return None

        assessment = self._assessor.assess(
            "",
            task_type,  # query not needed for type-only assessment
        )
        u = assessment.aggregated_u

        best_score = -1.0
        best_candidate = None

        for cand in candidates:
            capability = cand.get("capability", 0.5)
            soul = cand.get("soul_profile")

            # Personality match: default to neutral if no SOUL profile
            if soul is not None and isinstance(soul, SoulProfile):
                # Match decision style to task uncertainty
                if u >= 0.6:
                    # High uncertainty → prefer evidence-based, calibrated
                    style_score = 1.0 if soul.decision_style.value == "evidence_based" else 0.6
                elif u >= 0.3:
                    # Medium → balanced
                    style_score = 0.8
                else:
                    # Low → intuitive/fast is fine
                    style_score = 1.0 if soul.decision_speed > 0.5 else 0.7

                # Risk alignment: how well does Expert's risk appetite match?
                target_risk = user_risk_preference if user_risk_preference is not None else u
                risk_gap = abs(soul.risk_appetite - target_risk)
                risk_alignment = 1.0 - risk_gap

                personality = 0.6 * style_score + 0.4 * risk_alignment
            else:
                personality = 0.5  # Neutral default

            # Composite score
            score = 0.5 * capability + 0.3 * personality + 0.2 * (1.0 - abs(u - 0.5) * 0.5)

            if score > best_score:
                best_score = score
                best_candidate = cand

        return best_candidate

    def get_routing_config(self) -> dict[str, Any]:
        """Return full routing config for API/serialization."""
        return {
            "river_threshold": self._assessor.RIVER_THRESHOLD,
            "weights": {
                "semantic": self._assessor.W_SEMANTIC,
                "historical": self._assessor.W_HISTORICAL,
                "domain": self._assessor.W_DOMAIN,
            },
            "pipelines": {
                "village": [lid.value for lid in _VILLAGE_PIPELINE],
                "river": [lid.value for lid in _RIVER_PIPELINE],
                "river_deep": [lid.value for lid in _RIVER_DEEP_PIPELINE],
            },
            "mode_stats": self.get_mode_stats(),
        }
