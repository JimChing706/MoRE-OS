"""Silver Habits Engineering — Practical implementations of Silver's 13 habits.

Each habit is translated into a measurable, testable engineering pattern
that can be plugged into MoRE OS subsystems.

Mapping:
  Habit                    → Implementation
  ─────────────────────────────────────────────
  1. Probabilistic thinking → CalibratedConfidence output wrapper
  2. Emotional detachment   → TiltDetector (isolates emotional state)
  3. Continuous learning    → OnlineLearningHook (real-time capability update)
  4. Opponent modeling      → UserRiskProfiler (dynamic risk-preference model)
  5. Stop-loss discipline   → TripleCircuitBreaker (token/time/cost limits)
  6. Information value      → InfoCostBenefit (query cost vs expected value)
  7. Diversified betting    → ExpertDiversifier (anti-monopoly routing)
  8. Long-term perspective  → CumulativeRewardTracker
  9. Anti-fragility         → ChaosInjector (epsilon-random exploration)
  10. Edge advantage        → SpecializationScorer
  11. Network effects       → CollaborationBonus (synergy reward)
  12. Rapid iteration       → FastABTest (lightweight experiment framework)
  13. Exit strategy         → ConvergenceDetector (auto-termination)
"""

from __future__ import annotations

import logging
import time
import random
from dataclasses import dataclass, field

_log = logging.getLogger("more_core.v3.silver_habits")


# ── 1. Calibrated Confidence ─────────────────────────────────────────────


@dataclass
class CalibratedOutput:
    """Confidence-calibrated output wrapper (Habit #1: probabilistic thinking)."""

    answer: str
    confidence: float  # [0, 1] calibrated estimate
    confidence_interval: tuple[float, float]  # e.g. (0.6, 0.9)
    reasoning: str = ""
    alternatives: list[str] = field(default_factory=list)
    uncertainty_sources: list[str] = field(default_factory=list)

    def is_high_confidence(self, threshold: float = 0.8) -> bool:
        return self.confidence >= threshold

    def needs_validation(self) -> bool:
        """High-uncertainty answers should be cross-validated."""
        return (
            self.confidence < 0.6
            or (self.confidence_interval[1] - self.confidence_interval[0]) > 0.3
        )


# ── 5. Triple Circuit Breaker ────────────────────────────────────────────


@dataclass
class CircuitBreakerState:
    """Triple-limit circuit breaker (Habit #5: stop-loss discipline)."""

    token_limit: int
    time_limit_s: float
    cost_limit_usd: float
    tokens_used: int = 0
    time_started: float = field(default_factory=time.monotonic)
    cost_incurred: float = 0.0

    @property
    def token_remaining(self) -> int:
        return max(0, self.token_limit - self.tokens_used)

    @property
    def time_remaining(self) -> float:
        return max(0.0, self.time_limit_s - (time.monotonic() - self.time_started))

    @property
    def is_breached(self) -> bool:
        return (
            self.tokens_used >= self.token_limit
            or (time.monotonic() - self.time_started) >= self.time_limit_s
            or self.cost_incurred >= self.cost_limit_usd
        )

    def consume(self, tokens: int, cost: float = 0.0) -> bool:
        """Consume resources; returns False if breach would occur."""
        if self.tokens_used + tokens > self.token_limit:
            return False
        if self.cost_incurred + cost > self.cost_limit_usd:
            return False
        self.tokens_used += tokens
        self.cost_incurred += cost
        return True

    @property
    def breach_reason(self) -> str | None:
        if self.tokens_used >= self.token_limit:
            return f"token limit ({self.token_limit}) reached"
        if (time.monotonic() - self.time_started) >= self.time_limit_s:
            return f"time limit ({self.time_limit_s}s) reached"
        if self.cost_incurred >= self.cost_limit_usd:
            return f"cost limit (${self.cost_limit_usd:.4f}) reached"
        return None


# ── 2. Tilt Detector ─────────────────────────────────────────────────────


class TiltDetector:
    """Detects emotional 'tilt' in decision patterns (Habit #2: emotional detachment).

    Tracks outcome sequences and flags when consecutive failures
    might be influencing subsequent decisions.
    """

    def __init__(self, window_size: int = 5, tilt_threshold: float = 0.6) -> None:
        self._window: list[bool] = []  # True = success, False = failure
        self._window_size = window_size
        self._tilt_threshold = tilt_threshold

    def record_outcome(self, success: bool) -> None:
        self._window.append(success)
        if len(self._window) > self._window_size:
            self._window.pop(0)

    @property
    def is_tilting(self) -> bool:
        """Returns True if consecutive failures suggest emotional influence."""
        if len(self._window) < self._window_size:
            return False
        failures = sum(1 for s in self._window if not s)
        return failures / self._window_size >= self._tilt_threshold

    @property
    def streak_length(self) -> int:
        """Current consecutive failure streak length."""
        streak = 0
        for outcome in reversed(self._window):
            if not outcome:
                streak += 1
            else:
                break
        return streak

    def reset(self) -> None:
        self._window.clear()


# ── 9. Chaos Injector ────────────────────────────────────────────────────


class ChaosInjector:
    """Controlled randomness for anti-fragility (Habit #9: anti-fragility).

    Injects epsilon-random exploration to prevent local-optimum lock-in.
    """

    def __init__(self, epsilon: float = 0.05, decay: float = 0.9995) -> None:
        self.epsilon = epsilon
        self.decay = decay
        self._steps = 0

    def should_explore(self) -> bool:
        """Decide whether to explore (random) vs exploit (optimal)."""
        self._steps += 1
        current_epsilon = self.epsilon * (self.decay**self._steps)
        return random.random() < max(0.001, current_epsilon)

    @property
    def current_epsilon(self) -> float:
        return max(0.001, self.epsilon * (self.decay**self._steps))


# ── 13. Convergence Detector ─────────────────────────────────────────────


@dataclass
class ConvergenceSignal:
    """Auto-termination signal (Habit #13: exit strategy)."""

    should_terminate: bool
    reason: str
    current_iteration: int
    improvement_rate: float  # Δ quality per iteration
    stagnation_count: int  # Consecutive iterations without improvement


class ConvergenceDetector:
    """Detects when further iteration is no longer adding value.

    Implements Silver's 'exit strategy' — knowing when to fold.
    """

    def __init__(
        self,
        stagnation_threshold: int = 3,
        min_improvement: float = 0.01,
        max_iterations: int = 20,
    ) -> None:
        self._stagnation_threshold = stagnation_threshold
        self._min_improvement = min_improvement
        self._max_iterations = max_iterations
        self._history: list[float] = []  # Quality scores per iteration
        self._stagnation_count = 0

    def record_quality(self, quality: float) -> ConvergenceSignal:
        """Record a quality score and return convergence assessment."""
        self._history.append(quality)
        iteration = len(self._history)

        # Check max iterations
        if iteration >= self._max_iterations:
            return ConvergenceSignal(
                should_terminate=True,
                reason=f"max iterations ({self._max_iterations}) reached",
                current_iteration=iteration,
                improvement_rate=0.0,
                stagnation_count=self._stagnation_count,
            )

        # Check improvement
        if iteration >= 2:
            improvement = quality - self._history[-2]
            if improvement < self._min_improvement:
                self._stagnation_count += 1
            else:
                self._stagnation_count = 0

        if self._stagnation_count >= self._stagnation_threshold:
            return ConvergenceSignal(
                should_terminate=True,
                reason=f"stagnation: {self._stagnation_count} iterations without improvement",
                current_iteration=iteration,
                improvement_rate=(
                    (quality - self._history[0]) / iteration if iteration > 0 else 0.0
                ),
                stagnation_count=self._stagnation_count,
            )

        return ConvergenceSignal(
            should_terminate=False,
            reason="still improving",
            current_iteration=iteration,
            improvement_rate=((quality - self._history[0]) / iteration if iteration > 0 else 0.0),
            stagnation_count=self._stagnation_count,
        )

    def reset(self) -> None:
        self._history.clear()
        self._stagnation_count = 0


# ── 6. Information Cost-Benefit ──────────────────────────────────────────


class InfoCostBenefit:
    """Evaluates whether information acquisition is +EV (Habit #6: information value).

    Key insight from Silver: don't pursue perfect information;
    pursue information whose expected value exceeds its cost.
    """

    def __init__(self, cost_per_token: float = 0.000001) -> None:
        self._cost_per_token = cost_per_token

    def should_acquire(
        self,
        estimated_tokens: int,
        decision_impact: float,  # How much this info could change the outcome [0,1]
        current_uncertainty: float,  # Current U index [0,1]
    ) -> tuple[bool, str]:
        """Determine if acquiring more information is +EV.

        Returns (should_acquire, reasoning).
        """
        cost = estimated_tokens * self._cost_per_token
        # Expected value of information ≈ decision_impact × uncertainty_reduction
        # Uncertainty reduction is proportional to current uncertainty
        ev_info = decision_impact * current_uncertainty * 0.01  # Scale to USD

        if ev_info > cost:
            return True, f"+EV: info value ${ev_info:.5f} > cost ${cost:.5f}"
        else:
            return False, f"-EV: info value ${ev_info:.5f} ≤ cost ${cost:.5f}"


# ── 7. Expert Diversifier ────────────────────────────────────────────────


class ExpertDiversifier:
    """Prevents single-Expert monopoly (Habit #7: diversified betting).

    Tracks Expert usage frequency and injects diversity bonus
    to prevent over-reliance on a single Expert.
    """

    def __init__(self, diversity_weight: float = 0.15) -> None:
        self._usage: dict[str, int] = {}
        self._diversity_weight = diversity_weight

    def record_usage(self, expert_id: str) -> None:
        self._usage[expert_id] = self._usage.get(expert_id, 0) + 1

    def diversity_bonus(self, expert_id: str) -> float:
        """Return 0-1 diversity bonus: underused Experts get higher bonus."""
        total = sum(self._usage.values()) or 1
        frequency = self._usage.get(expert_id, 0) / total
        return self._diversity_weight * (1.0 - frequency)  # Less used → higher bonus

    def get_usage_stats(self) -> dict[str, int]:
        return dict(self._usage)


# ── 11. Collaboration Bonus ──────────────────────────────────────────────


class CollaborationBonus:
    """Rewards complementary Expert pairs (Habit #11: network effects).

    Tracks which Expert pairs produce above-average results and
    applies a synergy bonus to their routing scores.
    """

    def __init__(self, learning_rate: float = 0.1) -> None:
        self._pair_scores: dict[tuple[str, str], float] = {}  # (A, B) → synergy score
        self._lr = learning_rate

    def record_collaboration(self, expert_a: str, expert_b: str, outcome_quality: float) -> None:
        """Update synergy score for an Expert pair."""
        pair: tuple[str, str] = (
            (expert_a, expert_b) if expert_a <= expert_b else (expert_b, expert_a)
        )
        current = self._pair_scores.get(pair, 0.5)
        self._pair_scores[pair] = current + self._lr * (outcome_quality - current)

    def synergy_bonus(self, expert_a: str, expert_b: str) -> float:
        """Return synergy bonus for this pair (0 = no bonus, 1 = max synergy)."""
        pair: tuple[str, str] = (
            (expert_a, expert_b) if expert_a <= expert_b else (expert_b, expert_a)
        )
        return self._pair_scores.get(pair, 0.0)

    def top_pairs(self, n: int = 5) -> list[tuple[tuple[str, str], float]]:
        """Return top-N most synergistic Expert pairs."""
        sorted_pairs = sorted(self._pair_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_pairs[:n]
