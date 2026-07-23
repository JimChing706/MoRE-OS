"""Dynamic Guardrails — Uncertainty-Adaptive Constraint System for MoRE v3.0.

Replaces v2.0's static guardrails with uncertainty-aware adaptive constraints.

Core formula (西尔弗#5 止损纪律):
    intensity = U × criticality
    guardrail_strength = f(intensity)

Where:
  - U ∈ [0,1] is the task uncertainty from UncertaintyAssessor
  - criticality ∈ [0,1] is user-specified or task-inferred importance
  - f() maps intensity to concrete constraint values

Key insight: NOT all tasks are equally protected.  Protection budget
is proportional to risk exposure (U × criticality).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

_log = logging.getLogger("more_core.v3.dynamic_guardrails")


# ── Sandbox levels ───────────────────────────────────────────────────────


class SandboxLevel(str, Enum):
    LIGHT = "light"  # Minimum isolation, fast execution
    STANDARD = "standard"  # Default isolation
    STRICT = "strict"  # Command whitelist, output capping
    ISOLATED = "isolated"  # Full isolation, network/filesystem blocked


# ── Guardrail configuration ──────────────────────────────────────────────


@dataclass(slots=True)
class GuardrailConfig:
    """A complete set of guardrail settings for a request."""

    token_budget: int  # Max tokens for LLM calls
    timeout_s: float  # Max wall-clock time
    validation_layers: int  # How many validation passes (1-5)
    sandbox_level: SandboxLevel  # Code execution isolation level
    cross_validation_required: bool  # Whether to run cross-expert validation
    human_in_the_loop: bool  # Whether to pause for human approval
    max_experts: int  # Max concurrent experts
    max_parallel_calls: int  # Max parallel LLM calls
    max_cost_usd: float  # Budget cap in USD

    # Metadata
    intensity: float = 0.0  # U × criticality
    reasoning: str = ""  # Human-readable explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_budget": self.token_budget,
            "timeout_s": self.timeout_s,
            "validation_layers": self.validation_layers,
            "sandbox_level": self.sandbox_level.value,
            "cross_validation_required": self.cross_validation_required,
            "human_in_the_loop": self.human_in_the_loop,
            "max_experts": self.max_experts,
            "max_parallel_calls": self.max_parallel_calls,
            "max_cost_usd": self.max_cost_usd,
            "intensity": self.intensity,
            "reasoning": self.reasoning,
        }


# ── Base constraints (default floor) ────────────────────────────────────

_BASE_CONSTRAINTS = {
    "token_budget": 4096,
    "timeout_s": 30.0,
    "validation_layers": 1,
    "sandbox_level": SandboxLevel.STANDARD,
    "cross_validation_required": False,
    "human_in_the_loop": False,
    "max_experts": 1,
    "max_parallel_calls": 1,
    "max_cost_usd": 0.001,
}


# ── Intensity-to-level mapping ──────────────────────────────────────────


def _intensity_to_sandbox(intensity: float) -> SandboxLevel:
    if intensity < 0.2:
        return SandboxLevel.LIGHT
    elif intensity < 0.5:
        return SandboxLevel.STANDARD
    elif intensity < 0.75:
        return SandboxLevel.STRICT
    else:
        return SandboxLevel.ISOLATED


# ── Dynamic Guardrails ───────────────────────────────────────────────────


class DynamicGuardrails:
    """Adaptive constraint system that scales protection with risk.

    Usage::

        dg = DynamicGuardrails()
        config = dg.adjust(u=0.45, criticality=0.6)
        # config.token_budget → ~4000
        # config.sandbox_level → "standard"
    """

    def __init__(self, base_overrides: dict[str, Any] | None = None) -> None:
        self._base = dict(_BASE_CONSTRAINTS)
        if base_overrides:
            self._base.update(base_overrides)

    # ── Main adjustment API ──────────────────────────────────────────────

    def adjust(
        self,
        u: float,
        criticality: float = 0.5,
        *,
        hints: dict[str, Any] | None = None,
    ) -> GuardrailConfig:
        """Compute adaptive guardrail configuration for a task.

        Args:
            u: Uncertainty index [0,1] from UncertaintyAssessor
            criticality: Task criticality [0,1] (1 = mission-critical)
            hints: Optional pre-computed hints from MetaOrchestrator

        Returns:
            GuardrailConfig with all constraint values set
        """
        # Clamp inputs
        u = max(0.0, min(1.0, u))
        criticality = max(0.0, min(1.0, criticality))

        # Core formula: intensity = U × criticality
        intensity = u * criticality

        # Token budget scales with intensity
        # Low intensity → tight budget (1024), high → generous (16384)
        token_budget = int(1024 + intensity * 15360)

        # Timeout scales with intensity
        timeout_s = 15.0 + intensity * 105.0

        # Validation layers: 1 (floor) to 5 (ceiling)
        validation_layers = 1 + int(intensity * 4)

        # Sandbox level
        sandbox_level = _intensity_to_sandbox(intensity)

        # Cross-validation required for high-intensity tasks
        cross_validation_required = intensity > 0.4

        # Human-in-the-loop for very high intensity + high criticality
        human_in_the_loop = intensity > 0.6 and criticality > 0.7

        # Expert parallelism
        max_experts = 1 + int(intensity * 4)
        max_parallel_calls = 1 + int(intensity * 4)

        # Cost budget
        max_cost_usd = 0.001 + intensity * 0.015

        # Apply hints from MetaOrchestrator if provided
        if hints:
            token_budget = hints.get("token_budget", token_budget)
            timeout_s = hints.get("timeout_s", timeout_s)
            validation_layers = hints.get("validation_layers", validation_layers)
            sandbox_level = SandboxLevel(hints.get("sandbox_level", sandbox_level.value))
            cross_validation_required = hints.get(
                "cross_validation_required", cross_validation_required
            )
            human_in_the_loop = hints.get("human_in_the_loop", human_in_the_loop)
            max_experts = hints.get("max_experts", max_experts)

        # Reasoning
        reasoning = self._build_reasoning(u, criticality, intensity)

        _log.debug(
            "DynamicGuardrails: U=%.2f crit=%.2f intensity=%.2f → "
            "tokens=%d timeout=%.1fs validation=%d sandbox=%s",
            u,
            criticality,
            intensity,
            token_budget,
            timeout_s,
            validation_layers,
            sandbox_level.value,
        )

        return GuardrailConfig(
            token_budget=token_budget,
            timeout_s=timeout_s,
            validation_layers=validation_layers,
            sandbox_level=sandbox_level,
            cross_validation_required=cross_validation_required,
            human_in_the_loop=human_in_the_loop,
            max_experts=max_experts,
            max_parallel_calls=max_parallel_calls,
            max_cost_usd=max_cost_usd,
            intensity=intensity,
            reasoning=reasoning,
        )

    # ── Quick check API ──────────────────────────────────────────────────

    def is_light_mode(self, u: float, criticality: float) -> bool:
        """Check if task qualifies for light guardrails."""
        return (u * criticality) < 0.2

    def requires_human_approval(self, u: float, criticality: float) -> bool:
        """Check if task requires human-in-the-loop."""
        return (u * criticality) > 0.6 and criticality > 0.7

    # ── Intensity spectrum visualization ─────────────────────────────────

    def get_intensity_spectrum(self) -> dict[str, GuardrailConfig]:
        """Return sample configurations across the intensity spectrum.

        Useful for visualization / monitoring dashboards.
        """
        samples = {}
        for intensity in [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]:
            u = intensity  # Assume criticality=1 for worst-case
            config = self.adjust(u=u, criticality=1.0)
            samples[f"intensity_{intensity:.1f}"] = config
        return samples

    # ── Internal ─────────────────────────────────────────────────────────

    def _build_reasoning(self, u: float, criticality: float, intensity: float) -> str:
        """Build human-readable reasoning string."""
        if intensity < 0.1:
            level = "轻量"
        elif intensity < 0.3:
            level = "标准"
        elif intensity < 0.6:
            level = "增强"
        else:
            level = "严格"

        parts = [
            f"护栏强度={level}",
            f"U={u:.2f}",
            f"关键性={criticality:.2f}",
            f"风险敞口=intensity={intensity:.2f}",
        ]
        return ", ".join(parts)


# ── Convenience singleton ────────────────────────────────────────────────

_default_guardrails: DynamicGuardrails | None = None


def get_dynamic_guardrails() -> DynamicGuardrails:
    """Get or create the global DynamicGuardrails instance."""
    global _default_guardrails
    if _default_guardrails is None:
        _default_guardrails = DynamicGuardrails()
    return _default_guardrails


def reset_dynamic_guardrails() -> None:
    """Reset global instance (for testing)."""
    global _default_guardrails
    _default_guardrails = None
