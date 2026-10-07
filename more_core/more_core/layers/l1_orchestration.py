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


def _to_clamped_int(value: Any, default: int, lo: int = 0, hi: int = 10) -> int:
    """Best-effort cast to int clamped to ``[lo, hi]``.

    Any non-numeric / NaN / out-of-range input falls back to ``default`` then
    clamps.  Used on ``difficulty`` / ``capability`` so a dirty scratch write
    (str / NaN / out-of-band number) never breaks the L1 heuristic.
    """
    try:
        if isinstance(value, bool):
            v = int(value)
        elif value is None:
            v = default
        elif isinstance(value, (int, float)):
            v = round(float(value)) if isinstance(value, float) else int(value)
        else:
            v = int(str(value).strip())
    except (TypeError, ValueError, ArithmeticError):
        v = default
    return max(lo, min(hi, v))


def _safe_str(value: Any, default: str = "") -> str:
    """Best-effort str cast — never raises on weird inputs."""
    try:
        return default if value is None else str(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_plan(plan: Any) -> dict[str, Any]:
    return plan if isinstance(plan, dict) else {}


def _safe_context(request_context: Any) -> dict[str, Any]:
    return request_context if isinstance(request_context, dict) else {}


class OrchestrationLayer(Layer):
    layer_id = LayerId.L1

    # P1-2 A-1 方楫架构：OMAC plugin 激活结果 4 元组强契约
    # (mode, strategy, model_hint, token_budget) 缺一或类型错 → confidence=0.0
    _OMAC_REQUIRED_TUPLE: tuple[tuple[str, type], ...] = (
        ("mode", str),
        ("strategy", str),
        ("model_hint", str),
        ("token_budget", int),
    )
    _VALID_MODES = frozenset({"autonomous", "standard", "collaborative"})
    _VALID_STRATEGIES = frozenset(s.value for s in ExecutionStrategy)
    _VALID_MODEL_HINTS = frozenset(h.value for h in ModelHint)

    @classmethod
    def _validate_omac_output(cls, omac: Any) -> tuple[bool, str]:
        """Validate OMAC plugin output against the 4-tuple contract (A-1).

        Returns:
            (ok, reason) — ``reason`` is a short safe description intended for
            the ``description`` field only (never logged verbatim when the
            contract fails — 零原文原则兼容).
        """
        if not isinstance(omac, dict):
            return False, "omac output must be dict"
        for key, expected_type in cls._OMAC_REQUIRED_TUPLE:
            if key not in omac:
                return False, f"missing key: {key}"
            val = omac[key]
            if expected_type is int:
                if isinstance(val, bool) or not isinstance(val, int):
                    return False, f"bad type for {key}: expected int"
                if val <= 0:
                    return False, f"{key} must be > 0"
            elif not isinstance(val, expected_type):
                return False, f"bad type for {key}: expected {expected_type.__name__}"
        if omac["mode"] not in cls._VALID_MODES:
            return False, "mode not in {autonomous,standard,collaborative}"
        if omac["strategy"] not in cls._VALID_STRATEGIES:
            return False, "strategy not in ExecutionStrategy"
        if omac["model_hint"] not in cls._VALID_MODEL_HINTS:
            return False, "model_hint not in ModelHint"
        return True, "omac 4-tuple ok"

    async def process(self, ctx: LayerContext) -> LayerResult:
        try:
            difficulty = _to_clamped_int(ctx.scratch.get("difficulty"), 5)
            capability = _to_clamped_int(ctx.scratch.get("capability"), 7)
            _req_type = getattr(ctx.request, "type", None)
            is_code = _req_type in _CODE_TASK_TYPES
            is_reasoning = _req_type in _REASONING_TASK_TYPES
            has_subtasks = bool(_safe_plan(ctx.scratch.get("plan")).get("subtasks"))

            # P1-2 A-1：OMAC plugin 激活 → 4 元组校验 → 失败 confidence=0.0 回退启发式
            omac_output = ctx.scratch.get("omac_plugin_output", None)
            omac_ok = False
            omac_reason = "plugin not provided"
            if omac_output is not None:
                omac_ok, omac_reason = self._validate_omac_output(omac_output)
                if omac_ok:
                    mode = omac_output["mode"]
                    strategy = ExecutionStrategy(omac_output["strategy"])
                    model_hint = ModelHint(omac_output["model_hint"])
                    tokens = max(1, int(omac_output["token_budget"]))
                    # 由 OMAC 选 strategy → 推导 temp
                    if strategy is ExecutionStrategy.PRECISE:
                        temp = 0.3
                    elif strategy is ExecutionStrategy.CREATIVE:
                        temp = 0.8
                    else:
                        temp = 0.5 if is_reasoning else 0.6
                    confidence = 1.0
                    plan_source = f"omac-plugin ({omac_reason})"
                else:
                    # A-1 强制：4 元组失败 → confidence=0.0，完全回退启发式
                    confidence = 0.0
                    plan_source = f"omac-activation-failed confidence=0.0 ({omac_reason})"
                    omac_ok = False  # 继续跑启发式
            if not omac_ok:
                # 1. Execution mode — selected based on difficulty vs capability gap
                gap = difficulty - capability
                if gap >= 3:
                    mode = "collaborative"
                elif gap <= -2:
                    mode = "autonomous"
                else:
                    mode = "standard"

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
                model_hint = (
                    ModelHint.REASONING if is_reasoning and difficulty >= 6 else ModelHint.STANDARD
                )

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
                # OMAC 激活失败时：强制 confidence=0.0，启发式兜底（A-1 要求）
                confidence = 0.0 if (omac_output is not None and not omac_ok) else 0.9
                plan_source = "builtin-heuristic" if omac_output is None else plan_source

            # 5. Subtask orchestration hint (when L4 decomposed)
            if has_subtasks:
                subtasks = _safe_plan(ctx.scratch["plan"]).get("subtasks")
                if isinstance(subtasks, (list, tuple)):
                    ctx.scratch["subtask_count"] = len(subtasks)
                else:
                    ctx.scratch["subtask_count"] = 0
                    has_subtasks = False

            plan: dict[str, Any] = {
                "selected_agents": ctx.scratch.get("agents", ["primary"]),
                "difficulty": difficulty,
                "capability": capability,
                "mode": mode,
                "strategy": strategy.value,
                "model_hint": model_hint.value,
                "has_subtasks": has_subtasks,
                "source": plan_source,
            }
            ctx.scratch["orchestration_plan"] = plan

            # Propagate to L0 via context overrides (best-effort safe write)
            try:
                rctx = _safe_context(getattr(ctx.request, "context", None))
                rctx["temperature"] = temp
                rctx["max_tokens"] = tokens
                rctx["execution_strategy"] = strategy.value
                rctx["model_hint"] = model_hint.value
                if not isinstance(getattr(ctx.request, "context", None), dict):
                    ctx.request.context = rctx
            except Exception:  # noqa: BLE001, S110
                pass

            return LayerResult(
                layer=self.layer_id,
                description=(
                    f"strategy={strategy.value} mode={mode} "
                    f"temp={temp} tokens={tokens} "
                    f"model={model_hint.value}"
                    + (" subtasks" if has_subtasks else "")
                    + f" source={plan_source} conf={confidence}"
                ),
                output=plan,
                confidence=confidence,
            )
        except Exception:  # noqa: BLE001
            # L1 invariant: never raises under any input.  Fallback plan is
            # balanced / standard model with conservative medium tokens so the
            # rest of the pipeline still has something to work on.
            plan = {
                "selected_agents": ["primary"],
                "difficulty": 5,
                "capability": 7,
                "mode": "standard",
                "strategy": ExecutionStrategy.BALANCED.value,
                "model_hint": ModelHint.STANDARD.value,
                "has_subtasks": False,
                "source": "exception-fallback",
            }
            try:
                ctx.scratch["orchestration_plan"] = plan
            except Exception:  # noqa: BLE001, S110
                pass
            return LayerResult(
                layer=self.layer_id,
                description="strategy=balanced mode=standard temp=0.6 tokens=2048 "
                "model=standard (safe fallback)",
                output=plan,
                confidence=0.6,
            )
