"""Token consumption predictor — estimates LLM token usage for planning steps.

Uses historical data and heuristic models to predict token consumption,
enabling dynamic budget allocation across plan steps.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import ClassVar

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class TokenObservation:
    """Historical token usage observation."""

    task_type: str
    query_length: int
    estimated_tokens: int
    actual_tokens: int
    difficulty: int
    timestamp: float = 0.0


class TokenPredictor:
    """Predicts LLM token consumption using historical data + heuristics.

    Prediction model:
    - Base tokens from task type (empirical constants)
    - Scale by query complexity (length + keyword indicators)
    - Adjust using exponential moving average of prediction errors
    - Dynamic budget allocation: distribute remaining tokens proportionally
    """

    # Empirical base token consumption per task type
    _BASE_TOKENS: ClassVar[dict[str, int]] = {
        "code_generation": 2048,
        "code_debugging": 1536,
        "code_review": 1024,
        "math_reasoning": 1536,
        "nlp_task": 768,
        "data_analysis": 1024,
        "architecture_design": 2560,
        "multi_agent_orchestration": 1280,
        "self_improvement": 2048,
        "cross_domain_transfer": 2048,
        "plugin_defined": 1024,
    }

    # Tokens per character of input (average across tasks)
    _TOKENS_PER_CHAR = 0.35

    def __init__(self, history_window: int = 200) -> None:
        self._history: deque[TokenObservation] = deque(maxlen=history_window)
        self._ema_error: float = 0.0  # Exponential moving average of prediction error
        self._ema_alpha: float = 0.15  # Smoothing factor

    def predict(
        self,
        task_type: str,
        query_length: int,
        difficulty: int = 5,
        step_index: int = 0,
        total_steps: int = 1,
    ) -> int:
        """Predict token consumption for a single step.

        Args:
            task_type: Task type string (e.g. 'code_generation')
            query_length: Character length of the prompt/subtask
            difficulty: Task difficulty 1-10
            step_index: Position of step in plan (later steps tend to use more)
            total_steps: Total steps in plan

        Returns:
            Predicted token count
        """
        base = self._BASE_TOKENS.get(task_type, 1024)

        # Scale by query complexity
        query_contribution = int(query_length * self._TOKENS_PER_CHAR)

        # Difficulty multiplier (linear: 0.6x at diff=1, 1.5x at diff=10)
        diff_multiplier = 0.5 + (difficulty / 10.0)

        # Later steps in a plan tend to need more context
        position_factor = 1.0 + (step_index / max(total_steps, 1)) * 0.3

        raw_prediction = int((base + query_contribution) * diff_multiplier * position_factor)

        # Apply EMA correction from historical prediction errors
        corrected = int(raw_prediction * (1.0 + self._ema_error))

        return max(256, min(8192, corrected))  # Clamp to reasonable range

    def predict_plan_total(
        self,
        task_type: str,
        subtasks: list[str],
        difficulty: int = 5,
    ) -> list[int]:
        """Predict token consumption for each step in a plan.

        Returns:
            List of predicted tokens per step
        """
        total_steps = len(subtasks)
        return [
            self.predict(
                task_type=task_type,
                query_length=len(desc),
                difficulty=difficulty,
                step_index=i,
                total_steps=total_steps,
            )
            for i, desc in enumerate(subtasks)
        ]

    def observe(self, observation: TokenObservation) -> None:
        """Record actual token usage to improve future predictions."""
        self._history.append(observation)

        # Update EMA of relative prediction error
        if observation.estimated_tokens > 0:
            relative_error = (
                observation.actual_tokens - observation.estimated_tokens
            ) / observation.estimated_tokens
            self._ema_error = (
                self._ema_alpha * relative_error + (1 - self._ema_alpha) * self._ema_error
            )

    def allocate_budget(
        self,
        total_budget: int,
        predictions: list[int],
    ) -> list[int]:
        """Dynamically allocate a fixed token budget across steps.

        Uses proportional allocation with a minimum floor per step.
        If total predictions exceed budget, scales down proportionally.
        If under budget, distributes surplus to later (typically harder) steps.

        Args:
            total_budget: Total available tokens
            predictions: Predicted tokens per step

        Returns:
            Allocated tokens per step (sums to <= total_budget)
        """
        if not predictions:
            return []

        total_predicted = sum(predictions)
        n = len(predictions)
        min_per_step = 256  # Minimum allocation per step

        if total_predicted <= total_budget:
            # Under budget: allocate predictions + distribute surplus to later steps
            surplus = total_budget - total_predicted
            allocations = list(predictions)
            # Distribute surplus weighted toward later steps
            weights = [1.0 + i * 0.5 for i in range(n)]
            total_weight = sum(weights)
            for i in range(n):
                allocations[i] += int(surplus * weights[i] / total_weight)
            return allocations
        else:
            # Over budget: scale down proportionally, respect minimum floor
            scale = total_budget / total_predicted
            allocations = [max(min_per_step, int(p * scale)) for p in predictions]
            # If scaling causes total to exceed budget, trim from largest
            while sum(allocations) > total_budget:
                max_idx = allocations.index(max(allocations))
                allocations[max_idx] -= 64
            return allocations

    def get_accuracy_stats(self) -> dict[str, float]:
        """Get prediction accuracy statistics."""
        if not self._history:
            return {"mean_error_pct": 0.0, "ema_correction": self._ema_error, "observations": 0}

        errors = []
        for obs in self._history:
            if obs.estimated_tokens > 0:
                err = abs(obs.actual_tokens - obs.estimated_tokens) / obs.estimated_tokens
                errors.append(err)

        mean_err = sum(errors) / len(errors) if errors else 0.0
        return {
            "mean_error_pct": round(mean_err * 100, 1),
            "ema_correction": round(self._ema_error, 4),
            "observations": len(self._history),
        }
