"""L1 — Orchestration Layer (execution strategy, agent handoff, resource
budgeting).

Produces an **execution plan** that governs how L0 runs:

- **Execution strategy**: precise (low temperature, high determinism)
  vs creative (higher temperature, exploration) vs balanced.
- **Token budgeting**: difficulty-aware allocation that prevents truncation
  for code generation (v0.6.1) and complex reasoning tasks.
- **Model hints**: suggests reasoning vs standard model families.
- **Subtask orchestration**: when L4 decomposition is present, produces
  dependency-aware execution order hints.

Phase B will replace this layer with a full OMAC plugin.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..core.types import LayerId, TaskType
from .base import Layer, LayerContext, LayerResult


class ExecutionStrategy(str, Enum):
    PRECISE = "precise"  # low temp, deterministic, for debugging/math
    BALANCED = "balanced"  # moderate temp, general purpose
    CREATIVE = "creative"  # higher temp, exploration


class ModelHint(str, Enum):
    STANDARD = "standard"  # default instruction-following model
    REASONING = "reasoning"  # chain-of-thought / reasoning model


# Token budgets — aim for completion without truncation.
_TOKEN_LOW = 1024  # simple NLP tasks
_TOKEN_MEDIUM = 2048  # moderate difficulty text
_TOKEN_CODE_MIN = 4096  # minimum for any code output
_TOKEN_HIGH = 8192  # complex code / collaborative mode
_TOKEN_MAX = 16384  # extreme tasks (architecture, multi-file)

_CODE_TASK_TYPES = frozenset(
    {
        TaskType.CODE_GENERATION,
        TaskType.CODE_DEBUGGING,
        TaskType.CODE_REVIEW,
        TaskType.CODE_TESTING,
    }
)

_REASONING_TASK_TYPES = frozenset(
    {
        TaskType.MATH_REASONING,
        TaskType.ARCHITECTURE_DESIGN,
        TaskType.DATA_ANALYSIS,
    }
)


class OrchestrationLayer(Layer):
    layer_id = LayerId.L1

    async def process(self, ctx: LayerContext) -> LayerResult:
        difficulty = ctx.scratch.get("difficulty", 5)
        capability = ctx.scratch.get("capability", 7)
        is_code = ctx.request.type in _CODE_TASK_TYPES
        is_reasoning = ctx.request.type in _REASONING_TASK_TYPES
        has_subtasks = bool(ctx.scratch.get("plan", {}).get("subtasks"))

        # 1. Execution mode — selected based on difficulty vs capability gap
        gap = difficulty - capability
        if gap >= 3:
            mode = "collaborative"  # hard task, weak capability → assist
        elif gap <= -2:
            mode = "autonomous"  # easy task, strong capability → run free
        else:
            mode = "standard"  # balanced

        # 2. Execution strategy — guides L0 temperature & behaviour
        if is_reasoning or mode == "collaborative":
            strategy = ExecutionStrategy.PRECISE
        elif is_code and difficulty >= 6:
            strategy = ExecutionStrategy.BALANCED
        elif difficulty <= 3:
            strategy = ExecutionStrategy.CREATIVE
        else:
            strategy = ExecutionStrategy.BALANCED

        # 3. Model hint — when reasoning tasks need a chain-of-thought model
        model_hint = ModelHint.REASONING if is_reasoning and difficulty >= 6 else ModelHint.STANDARD

        # 4. Token budget — derived from strategy + mode + code flag
        match strategy:
            case ExecutionStrategy.PRECISE:
                temp = 0.3
                tokens = _TOKEN_HIGH if is_code else _TOKEN_MEDIUM
            case ExecutionStrategy.CREATIVE:
                temp = 0.8
                tokens = _TOKEN_CODE_MIN if is_code else _TOKEN_MEDIUM
            case _:  # BALANCED
                temp = 0.5 if is_reasoning else 0.6
                tokens = _TOKEN_CODE_MIN if is_code else _TOKEN_MEDIUM

        # Difficulty overrides — high-complexity tasks need more tokens
        if difficulty >= 8:
            tokens = max(tokens, _TOKEN_HIGH)
            if is_code:
                tokens = max(tokens, _TOKEN_MAX)
        elif difficulty >= 5 and is_code:
            tokens = max(tokens, _TOKEN_CODE_MIN)

        # Collaborative mode — tighter temp, max budget
        if mode == "collaborative":
            temp = min(temp, 0.4)
            tokens = _TOKEN_HIGH

        # 5. Subtask orchestration hint (when L4 decomposed)
        if has_subtasks:
            subtasks = ctx.scratch["plan"]["subtasks"]
            ctx.scratch["subtask_count"] = len(subtasks)

        plan: dict[str, Any] = {
            "selected_agents": ctx.scratch.get("agents", ["primary"]),
            "difficulty": difficulty,
            "capability": capability,
            "mode": mode,
            "strategy": strategy.value,
            "model_hint": model_hint.value,
            "has_subtasks": has_subtasks,
        }
        ctx.scratch["orchestration_plan"] = plan

        # Propagate to L0 via context overrides
        ctx.request.context["temperature"] = temp
        ctx.request.context["max_tokens"] = tokens
        ctx.request.context["execution_strategy"] = strategy.value
        ctx.request.context["model_hint"] = model_hint.value

        return LayerResult(
            layer=self.layer_id,
            description=(
                f"strategy={strategy.value} mode={mode} "
                f"temp={temp} tokens={tokens} "
                f"model={model_hint.value}" + (" subtasks" if has_subtasks else "")
            ),
            output=plan,
            confidence=0.9,
        )
