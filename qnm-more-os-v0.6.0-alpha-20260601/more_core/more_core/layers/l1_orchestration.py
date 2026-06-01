"""L1 — Orchestration Layer (difficulty-aware routing, agent handoff).

Produces an execution plan that tunes L0 parameters based on task complexity:
- **single-agent**: standard generation with tuned temperature/tokens.
- **collaborative**: higher token budget, lower temperature for precision.

Full OMAC optimisation is delivered in Phase B as a plugin replacing this layer.
"""

from __future__ import annotations

from ..core.types import LayerId
from .base import Layer, LayerContext, LayerResult


class OrchestrationLayer(Layer):
    layer_id = LayerId.L1

    async def process(self, ctx: LayerContext) -> LayerResult:
        difficulty = ctx.scratch.get("difficulty", 5)
        capability = ctx.scratch.get("capability", 7)
        mode = "single-agent" if difficulty <= capability else "collaborative"

        # Derive execution parameters from difficulty assessment
        if mode == "collaborative" or difficulty >= 8:
            exec_temperature = 0.4  # Lower temperature for complex reasoning
            exec_max_tokens = 4096  # Higher budget for multi-step tasks
        elif difficulty >= 5:
            exec_temperature = 0.6
            exec_max_tokens = 2048
        else:
            exec_temperature = 0.7
            exec_max_tokens = 1024

        plan = {
            "selected_agents": ctx.scratch.get("agents", ["primary"]),
            "difficulty": difficulty,
            "capability": capability,
            "mode": mode,
        }
        ctx.scratch["orchestration_plan"] = plan
        # Propagate to L0 via context overrides — direct assignment ensures
        # L1's difficulty-based tuning is authoritative, not silently overridden
        # by user-supplied context values.
        ctx.request.context["temperature"] = exec_temperature
        ctx.request.context["max_tokens"] = exec_max_tokens

        return LayerResult(
            layer=self.layer_id,
            description=f"routing: {mode} (d={difficulty}, c={capability}) → temp={exec_temperature} tokens={exec_max_tokens}",
            output=plan,
            confidence=0.9,
        )
