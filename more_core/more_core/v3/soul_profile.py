"""SOUL Profile — Expert Personality Model for MoRE v3.0.

Encodes Dr. Nate Silver's "13 habits of successful risk-takers" as
quantifiable Expert personality traits, enabling personality-aware
routing in the Meta-Orchestrator.

Personality dimensions are independent of capability — an Expert can be
highly capable but overconfident, or lower-capability but well-calibrated.
The Meta-Orchestrator weights both dimensions when routing tasks.

Design principle (西尔弗#1 概率思维):
    Every SOUL trait is treated as a probability distribution,
    not a fixed label.  Two Experts with "calibrated" confidence
    may express it with different variance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── Silver Habits (13) ───────────────────────────────────────────────────


class SilverHabit(str, Enum):
    """Dr. Nate Silver's 13 habits of successful risk-takers."""

    # 1. Probabilistic thinking
    PROBABILISTIC_THINKING = "probabilistic_thinking"
    # 2. Emotional detachment
    EMOTIONAL_DETACHMENT = "emotional_detachment"
    # 3. Continuous learning
    CONTINUOUS_LEARNING = "continuous_learning"
    # 4. Opponent modeling (user/environment)
    OPPONENT_MODELING = "opponent_modeling"
    # 5. Stop-loss discipline
    STOP_LOSS_DISCIPLINE = "stop_loss_discipline"
    # 6. Information value assessment
    INFO_VALUE_ASSESSMENT = "info_value_assessment"
    # 7. Diversified betting
    DIVERSIFIED_BETTING = "diversified_betting"
    # 8. Long-term perspective
    LONG_TERM_PERSPECTIVE = "long_term_perspective"
    # 9. Anti-fragility
    ANTI_FRAGILITY = "anti_fragility"
    # 10. Edge advantage
    EDGE_ADVANTAGE = "edge_advantage"
    # 11. Network effects
    NETWORK_EFFECTS = "network_effects"
    # 12. Rapid iteration
    RAPID_ITERATION = "rapid_iteration"
    # 13. Exit strategy
    EXIT_STRATEGY = "exit_strategy"


# ── Decision style ───────────────────────────────────────────────────────


class DecisionStyle(str, Enum):
    EVIDENCE_BASED = "evidence_based"  # Data-driven, cautious
    INTUITIVE = "intuitive"  # Pattern-matching, fast
    CONSENSUS = "consensus"  # Seeks agreement, collaborative
    ADVERSARIAL = "adversarial"  # Challenges assumptions, contrarian


class ConfidenceStyle(str, Enum):
    CALIBRATED = "calibrated"  # Confidence tracks accuracy
    OVERCONFIDENT = "overconfident"  # Confidence > accuracy
    UNDERCONFIDENT = "underconfident"  # Confidence < accuracy
    VARIABLE = "variable"  # Depends on domain


class RecoveryStyle(str, Enum):
    AGGRESSIVE = "aggressive"  # Double down after failure
    CONSERVATIVE = "conservative"  # Reduce exposure after failure
    ADAPTIVE = "adaptive"  # Adjust based on failure pattern


class CollaborationPreference(str, Enum):
    PEER = "peer"  # Works best as equal partner
    HIERARCHICAL = "hierarchical"  # Works best with clear leader
    SOLO = "solo"  # Works best independently
    MENTOR = "mentor"  # Works best guiding others


# ── SOUL Profile ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class SoulProfile:
    """Personality profile for an Expert (Agent/Hand).

    All traits are on [0,1] scale unless otherwise noted.
    """

    # ── Core personality axes ──────────────────────────────────────────
    risk_appetite: float = 0.5  # 0=极度保守, 1=极度激进
    creativity: float = 0.5  # 0=模板化, 1=高度创新
    verbosity: float = 0.5  # 0=极简回答, 1=详尽解释
    formality: float = 0.5  # 0=随性口语, 1=学术正式

    # ── Decision-making traits ─────────────────────────────────────────
    decision_style: DecisionStyle = DecisionStyle.EVIDENCE_BASED
    decision_speed: float = 0.5  # 0=深思熟虑, 1=快速决断
    confidence_style: ConfidenceStyle = ConfidenceStyle.CALIBRATED
    confidence_baseline: float = 0.7  # Default confidence level [0,1]

    # ── Resilience traits ──────────────────────────────────────────────
    failure_recovery: RecoveryStyle = RecoveryStyle.ADAPTIVE
    resilience: float = 0.7  # 0=易受挫折, 1=极强韧性
    adaptability: float = 0.6  # 0=固守模式, 1=灵活适应

    # ── Collaboration traits ───────────────────────────────────────────
    collaboration_preference: CollaborationPreference = CollaborationPreference.PEER
    cooperativeness: float = 0.7  # 0=高度竞争, 1=高度合作
    assertiveness: float = 0.5  # 0=被动接受, 1=主动主导

    # ── Active Silver habits ───────────────────────────────────────────
    habits: list[SilverHabit] = field(
        default_factory=lambda: [
            SilverHabit.PROBABILISTIC_THINKING,
            SilverHabit.STOP_LOSS_DISCIPLINE,
            SilverHabit.CONTINUOUS_LEARNING,
        ]
    )

    # ── Metadata ───────────────────────────────────────────────────────
    name: str = ""  # Personality archetype name
    description: str = ""  # Natural-language summary
    tags: list[str] = field(default_factory=list)  # Searchable tags

    def habit_strength(self, habit: SilverHabit) -> float:
        """Return 0-1 strength for a specific habit.

        Habits not in the active list default to 0.2 (baseline).
        """
        if habit in self.habits:
            return 0.8  # Active habits are strong
        return 0.2  # Inactive habits have baseline presence

    def personality_vector(self) -> list[float]:
        """Return a normalized personality vector for routing similarity."""
        return [
            self.risk_appetite,
            self.creativity,
            self.decision_speed,
            self.resilience,
            self.adaptability,
            self.cooperativeness,
            self.assertiveness,
        ]

    def personality_match_score(self, other: SoulProfile) -> float:
        """Compute cosine similarity between two personality vectors."""
        v1 = self.personality_vector()
        v2 = other.personality_vector()
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.5
        result: float = max(0.0, min(1.0, dot / (norm1 * norm2)))
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk_appetite": self.risk_appetite,
            "creativity": self.creativity,
            "verbosity": self.verbosity,
            "formality": self.formality,
            "decision_style": self.decision_style.value,
            "decision_speed": self.decision_speed,
            "confidence_style": self.confidence_style.value,
            "confidence_baseline": self.confidence_baseline,
            "failure_recovery": self.failure_recovery.value,
            "resilience": self.resilience,
            "adaptability": self.adaptability,
            "collaboration_preference": self.collaboration_preference.value,
            "cooperativeness": self.cooperativeness,
            "assertiveness": self.assertiveness,
            "habits": [h.value for h in self.habits],
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SoulProfile:
        habits = [SilverHabit(h) for h in data.get("habits", [])]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            risk_appetite=float(data.get("risk_appetite", 0.5)),
            creativity=float(data.get("creativity", 0.5)),
            verbosity=float(data.get("verbosity", 0.5)),
            formality=float(data.get("formality", 0.5)),
            decision_style=DecisionStyle(data.get("decision_style", "evidence_based")),
            decision_speed=float(data.get("decision_speed", 0.5)),
            confidence_style=ConfidenceStyle(data.get("confidence_style", "calibrated")),
            confidence_baseline=float(data.get("confidence_baseline", 0.7)),
            failure_recovery=RecoveryStyle(data.get("failure_recovery", "adaptive")),
            resilience=float(data.get("resilience", 0.7)),
            adaptability=float(data.get("adaptability", 0.6)),
            collaboration_preference=CollaborationPreference(
                data.get("collaboration_preference", "peer")
            ),
            cooperativeness=float(data.get("cooperativeness", 0.7)),
            assertiveness=float(data.get("assertiveness", 0.5)),
            habits=habits,
            tags=data.get("tags", []),
        )


# ── Pre-built archetypes ────────────────────────────────────────────────

# These are ready-to-use personality templates mapped to Silver's framework.

ARCHETYPE_RISK_ANALYST = SoulProfile(
    name="风险分析师",
    description="Evidence-driven, well-calibrated, cautious but precise.  "
    "Embodies probabilistic thinking and stop-loss discipline.",
    risk_appetite=0.3,
    creativity=0.3,
    verbosity=0.7,
    formality=0.8,
    decision_style=DecisionStyle.EVIDENCE_BASED,
    decision_speed=0.3,
    confidence_style=ConfidenceStyle.CALIBRATED,
    confidence_baseline=0.6,
    failure_recovery=RecoveryStyle.CONSERVATIVE,
    resilience=0.6,
    adaptability=0.5,
    collaboration_preference=CollaborationPreference.PEER,
    cooperativeness=0.6,
    assertiveness=0.4,
    habits=[
        SilverHabit.PROBABILISTIC_THINKING,
        SilverHabit.STOP_LOSS_DISCIPLINE,
        SilverHabit.INFO_VALUE_ASSESSMENT,
        SilverHabit.LONG_TERM_PERSPECTIVE,
    ],
    tags=["analytical", "precise", "risk-aware"],
)

ARCHETYPE_INNOVATOR = SoulProfile(
    name="创新探索者",
    description="High-risk, high-creativity, intuitive decision-maker.  "
    "Embodies diversified betting and anti-fragility.",
    risk_appetite=0.8,
    creativity=0.9,
    verbosity=0.6,
    formality=0.3,
    decision_style=DecisionStyle.INTUITIVE,
    decision_speed=0.8,
    confidence_style=ConfidenceStyle.OVERCONFIDENT,
    confidence_baseline=0.8,
    failure_recovery=RecoveryStyle.AGGRESSIVE,
    resilience=0.9,
    adaptability=0.8,
    collaboration_preference=CollaborationPreference.SOLO,
    cooperativeness=0.4,
    assertiveness=0.8,
    habits=[
        SilverHabit.DIVERSIFIED_BETTING,
        SilverHabit.ANTI_FRAGILITY,
        SilverHabit.RAPID_ITERATION,
        SilverHabit.EDGE_ADVANTAGE,
    ],
    tags=["creative", "bold", "fast"],
)

ARCHETYPE_DIPLOMAT = SoulProfile(
    name="协调外交官",
    description="Consensus-builder, highly cooperative, emotionally detached.  "
    "Embodies network effects and opponent modeling.",
    risk_appetite=0.4,
    creativity=0.4,
    verbosity=0.8,
    formality=0.7,
    decision_style=DecisionStyle.CONSENSUS,
    decision_speed=0.4,
    confidence_style=ConfidenceStyle.CALIBRATED,
    confidence_baseline=0.65,
    failure_recovery=RecoveryStyle.ADAPTIVE,
    resilience=0.7,
    adaptability=0.7,
    collaboration_preference=CollaborationPreference.PEER,
    cooperativeness=0.9,
    assertiveness=0.5,
    habits=[
        SilverHabit.NETWORK_EFFECTS,
        SilverHabit.OPPONENT_MODELING,
        SilverHabit.EMOTIONAL_DETACHMENT,
        SilverHabit.EXIT_STRATEGY,
    ],
    tags=["collaborative", "diplomatic", "patient"],
)

ARCHETYPE_ENGINEER = SoulProfile(
    name="执行工程师",
    description="Systematic, precise, rapid iteration.  "
    "Embodies continuous learning and edge advantage.",
    risk_appetite=0.5,
    creativity=0.5,
    verbosity=0.4,
    formality=0.6,
    decision_style=DecisionStyle.EVIDENCE_BASED,
    decision_speed=0.6,
    confidence_style=ConfidenceStyle.CALIBRATED,
    confidence_baseline=0.7,
    failure_recovery=RecoveryStyle.ADAPTIVE,
    resilience=0.8,
    adaptability=0.6,
    collaboration_preference=CollaborationPreference.HIERARCHICAL,
    cooperativeness=0.6,
    assertiveness=0.6,
    habits=[
        SilverHabit.CONTINUOUS_LEARNING,
        SilverHabit.RAPID_ITERATION,
        SilverHabit.EDGE_ADVANTAGE,
        SilverHabit.STOP_LOSS_DISCIPLINE,
    ],
    tags=["systematic", "precise", "builder"],
)

# ── Archetype registry ──────────────────────────────────────────────────

_ARCHETYPES: dict[str, SoulProfile] = {
    "risk_analyst": ARCHETYPE_RISK_ANALYST,
    "innovator": ARCHETYPE_INNOVATOR,
    "diplomat": ARCHETYPE_DIPLOMAT,
    "engineer": ARCHETYPE_ENGINEER,
}


def get_archetype(name: str) -> SoulProfile | None:
    """Get a pre-built personality archetype by name."""
    return _ARCHETYPES.get(name)


def list_archetypes() -> list[str]:
    """List available archetype names."""
    return list(_ARCHETYPES.keys())


def register_archetype(name: str, profile: SoulProfile) -> None:
    """Register a custom archetype."""
    _ARCHETYPES[name] = profile
