"""Task-aware model router with intelligent fallback.

Routes different task types to appropriate models:
- Simple tasks (NLP, data analysis) → Ollama qwen2.5:7b (fast, cheap)
- Complex tasks (code generation, architecture) → LM Studio large model (capable)
- Math reasoning → LM Studio reasoning model
- Self-improvement / orchestration → LM Studio large model
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from ..core.types import TaskType
from .manager import ProviderModelPair as ModelBinding

__all__: list[str] = [
    "ModelBinding",
    "TASK_MODEL_MAP",
    "FALLBACK_BINDING",
    "TaskModelRouter",
]

if TYPE_CHECKING:
    from ..llm.manager import LLMManager

# Model identifiers — Ornith-1.5 family (LM Studio, both models local)
DEFAULT_LM_MODEL = "ornith-1.5-35b-a3b"  # 通用主力 (35B MoE, ~3B active)
DEFAULT_LM_REASONING_MODEL = (  # 本地推理蒸馏 35B MoE — 真实思考模型 (thinking 全开)
    "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
)
DEFAULT_LM_CODER_MODEL = "ornith-1.5-35b-a3b"  # 代码专用 (agentic coding SOTA)
DEFAULT_LM_SMALL_MODEL = "ornith-ai/ornith-1.5-9b"  # 轻量快速 (9B dense)
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"

# ── 逐级降智阶梯 (capability tier ladder, index 0 = strongest) ───────────
# 基于本地实测模型特性 (2026-08):
#   - 35B MoE (~3B active) 生成速度实际快于 9B dense → 旧 T2(9b) 实为"降智又降速"
#   - ornith / qwen 推理模型 thinking 无法通过 API 关闭, 每次请求都烧 30~150+
#     推理 token (≈30s 延迟主因) → 简单任务应避开 thinking 模型 (T2/T3),
#     高难度任务则要给足 max_tokens 预算, 否则 thinking 会吃光输出预算
#   - 两个 35B MoE 无法同时驻留 VRAM → T0/T1 保持同一 MoE 家族, 减少模型切换
# 每级可经环境变量覆盖: MORE_TIER_{0..3}_MODEL=provider:model
_TIER_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("lmstudio", DEFAULT_LM_REASONING_MODEL),  # T0 推理 — 最难推理/架构
    ("lmstudio", DEFAULT_LM_MODEL),  # T1 主力 — 代码/编排/默认
    ("lmstudio", DEFAULT_LM_SMALL_MODEL),  # T2 轻量 — 简单任务 (避开 thinking 开销)
    ("ollama", DEFAULT_OLLAMA_MODEL),  # T3 兜底 — 资源隔离的最后防线
)
# 每级生成策略 (性能平衡):
#   thinking   — 推理/主力开 (对支持 API 关闭的模型生效), 轻量/兜底关
#   max_tokens — 高难度给足预算 (thinking 占用输出预算), 低难度限制输出避免浪费
_TIER_THINKING: tuple[bool, ...] = (True, True, False, False)
_TIER_MAX_TOKENS: tuple[int, ...] = (8192, 4096, 2048, 1024)


def _parse_tier_config(
    env: dict[str, str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Load the tier ladder from env (``MORE_TIER_{0..3}_MODEL=provider:model``).

    A bare model name (no ``:``) keeps the tier's default provider (tiers 0-2
    → lmstudio, tier 3 → ollama).  Missing/malformed entries fall back to
    defaults.  Returns ``(models, providers)`` aligned tuples.
    """
    env = dict(os.environ) if env is None else env
    models: list[str] = []
    providers: list[str] = []
    for i, (def_provider, def_model) in enumerate(_TIER_DEFAULTS):
        raw = env.get(f"MORE_TIER_{i}_MODEL")
        if not raw:
            providers.append(def_provider)
            models.append(def_model)
            continue
        if ":" in raw:
            provider, model = raw.split(":", 1)
            provider, model = provider.strip(), model.strip()
        else:
            provider, model = def_provider, raw.strip()
        providers.append(provider or def_provider)
        models.append(model or def_model)
    return tuple(models), tuple(providers)


def _parse_prev_tier_config(
    env: dict[str, str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """P1-4 G-1 覃朗：前版梯子从环境变量 MORE_PREV_TIER_{0..3}_MODEL 加载。

    用于灰度发布后，经 RBAC 受控 rollback API 一键切回上一版 (G-2)。未配置则
    回退为当前版，保证永不出现空梯子。
    """
    env = dict(os.environ) if env is None else env
    models: list[str] = []
    providers: list[str] = []
    for i, (def_provider, def_model) in enumerate(_TIER_DEFAULTS):
        prev_raw = env.get(f"MORE_PREV_TIER_{i}_MODEL")
        cur_raw = env.get(f"MORE_TIER_{i}_MODEL")
        raw = prev_raw if prev_raw else cur_raw
        if not raw:
            providers.append(def_provider)
            models.append(def_model)
            continue
        if ":" in raw:
            provider, model = raw.split(":", 1)
            provider, model = provider.strip(), model.strip()
        else:
            provider, model = def_provider, raw.strip()
        providers.append(provider or def_provider)
        models.append(model or def_model)
    return tuple(models), tuple(providers)


MODEL_TIER_LADDER, TIER_PROVIDERS = _parse_tier_config()
PREV_MODEL_TIER_LADDER, PREV_TIER_PROVIDERS = _parse_prev_tier_config()
TIER_THINKING = _TIER_THINKING
TIER_MAX_TOKENS = _TIER_MAX_TOKENS
# G-1：把 PREV 梯子名导出让 dynamic_router / router status 可见
__all__.extend(["PREV_MODEL_TIER_LADDER", "PREV_TIER_PROVIDERS"])


# ── R1: Tier cooldown (anti-oscillation) + T0 whitelist ─────────────────

_DEFAULT_COOLDOWN_S = 30.0
_DEFAULT_REASONING_TASK_TYPES_CSV = "MATH_REASONING,ARCHITECTURE_DESIGN,DATA_ANALYSIS"


def _parse_cooldown_s(env: dict[str, str] | None = None) -> float:
    env = dict(os.environ) if env is None else env
    raw = env.get("MORE_TIER_SWITCH_COOLDOWN_S")
    if not raw:
        return _DEFAULT_COOLDOWN_S
    try:
        v = float(raw)
    except ValueError:
        _log_cfg.warning(
            "invalid MORE_TIER_SWITCH_COOLDOWN_S=%r → using default %.1fs",
            raw,
            _DEFAULT_COOLDOWN_S,
        )
        return _DEFAULT_COOLDOWN_S
    return max(0.0, v)


def _parse_t0_whitelist(env: dict[str, str] | None = None) -> frozenset[TaskType]:
    """Parse ``MORE_REASONING_TIER_TASK_TYPES`` (comma-separated TaskType names).

    Any TaskType NOT in this whitelist will be capped at tier 1 even when the
    difficulty classifier says 8+ (覃朗专家 R1-B 限流加固).  Unknown names
    are skipped with a warning.
    """
    env = dict(os.environ) if env is None else env
    raw = env.get("MORE_REASONING_TIER_TASK_TYPES", _DEFAULT_REASONING_TASK_TYPES_CSV)
    out: set[TaskType] = set()
    for piece in raw.split(","):
        name = piece.strip().upper()
        if not name:
            continue
        try:
            out.add(TaskType(name.lower()))
        except ValueError:
            _log_cfg.warning(
                "MORE_REASONING_TIER_TASK_TYPES: unknown TaskType %r ignored",
                name,
            )
    if not out:
        # Defensive floor — never empty; use the three canonical names
        return frozenset(
            {
                TaskType.MATH_REASONING,
                TaskType.ARCHITECTURE_DESIGN,
                TaskType.DATA_ANALYSIS,
            }
        )
    return frozenset(out)


# Module-level logger for config parsing warnings.  `TaskModelRouter` has its
# own instance logger for runtime routing.
_log_cfg = logging.getLogger(__name__)

TIER_SWITCH_COOLDOWN_S = _parse_cooldown_s()
T0_TASK_WHITELIST = _parse_t0_whitelist()


def _parse_tier0_disabled(env: dict[str, str] | None = None) -> bool:
    """Parse ``MORE_DISABLE_TIER_0`` — compliance hard switch (沈慎专家 S-5 / 覃朗 R3-B).

    Values "1", "true", "yes", "on" (case-insensitive) enable the switch and
    re-map tier-0 model to tier-1 so chain-of-thought reasoning models are
    completely bypassed (甲方合规场景: "no CoT model allowed").  Any other
    value or unset disables it.
    """
    env = dict(os.environ) if env is None else env
    raw = env.get("MORE_DISABLE_TIER_0", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


TIER_0_DISABLED = _parse_tier0_disabled()

# If the Tier 0 hard-disable switch is on, alias Tier 0 → Tier 1 on the
# module-level ladder so *every* downstream user of MODEL_TIER_LADDER /
# TIER_THINKING / TIER_MAX_TOKENS automatically obeys the switch.
if TIER_0_DISABLED:
    _ladder = list(MODEL_TIER_LADDER)
    _providers = list(TIER_PROVIDERS)
    _thinking = list(TIER_THINKING)
    _max_tokens = list(TIER_MAX_TOKENS)
    # T0 := T1 (everything copies, so route never hits reasoning-distilled)
    _ladder[0] = _ladder[1]
    _providers[0] = _providers[1]
    _thinking[0] = _thinking[1]
    _max_tokens[0] = _max_tokens[1]
    MODEL_TIER_LADDER = tuple(_ladder)
    TIER_PROVIDERS = tuple(_providers)
    TIER_THINKING = tuple(_thinking)
    TIER_MAX_TOKENS = tuple(_max_tokens)
    _log_cfg.warning(
        "MORE_DISABLE_TIER_0=1 active: Tier 0 (JEV reasoning-distilled) has been "
        "remapped to Tier 1.  No requests will ever route to the CoT family.",
    )


def tier_index_for_difficulty(difficulty: int | None) -> int:
    """Map task difficulty (0-10) → capability tier index (0 = strongest).

    - difficulty >= 8 (复杂): T0 推理蒸馏 35B MoE (thinking 全开)
    - difficulty >= 5 (中等): T1 主力 35B MoE
    - else (简单/琐碎): T2 轻量 (避开 thinking 开销)
    """
    if difficulty is None:
        return 1  # 默认主力
    if difficulty >= 8:
        return 0
    if difficulty >= 5:
        return 1
    return 2


# ── Task-to-model routing ────────────────────────────────────────────────
# 并行优势策略（都在 LM Studio）：
#   - 简单任务 → ornith-1.5-9b（快）
#   - 代码/推理/编排 → ornith-1.5-35b-a3b（强）

TASK_MODEL_MAP: dict[TaskType, ModelBinding] = {
    # 代码任务 → 35B coder（agentic coding 领先）
    TaskType.CODE_GENERATION: ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
    TaskType.CODE_DEBUGGING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CODE_REVIEW: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CODE_TESTING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
    # 数学/架构 → 35B 推理
    TaskType.MATH_REASONING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL),
    TaskType.ARCHITECTURE_DESIGN: ModelBinding(
        provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL
    ),
    # 简单任务 → 9B（快）
    TaskType.NLP_TASK: ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
    TaskType.DATA_ANALYSIS: ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
    # 编排/元任务 → 35B
    TaskType.MULTI_AGENT_ORCHESTRATION: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.SELF_IMPROVEMENT: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CROSS_DOMAIN_TRANSFER: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.PLUGIN_DEFINED: ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
}

FALLBACK_BINDING = ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL)

# ── Fallback chains ──────────────────────────────────────────────────────
# When primary model fails, try alternatives in order.

FALLBACK_CHAINS: dict[str, list[ModelBinding]] = {
    # LM Studio 35B → 9B → Ollama 兜底
    "lmstudio_primary": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    ],
    # Ollama 优先 → LM Studio 备选
    "ollama_primary": [
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
    ],
    # 推理任务 → 35B 优先
    "reasoning": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    ],
    # 代码任务 → 35B coder 优先，9B 兜底
    "code_primary": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_SMALL_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    ],
}


class TaskModelRouter:
    """Routes task types to specialized models with intelligent fallback."""

    def __init__(self, llm_manager: "LLMManager") -> None:
        self._llm = llm_manager
        self._task_map = dict(TASK_MODEL_MAP)
        self._logger = logging.getLogger(__name__)
        self._failure_count: dict[str, int] = {}

    def get_binding(self, task_type: TaskType) -> ModelBinding:
        """Get model binding for task type."""
        return self._task_map.get(task_type, FALLBACK_BINDING)

    def select_provider(self, task_type: TaskType) -> str | None:
        """Select best provider for task type."""
        binding = self.get_binding(task_type)
        if binding.provider in self._llm.list_providers():
            return binding.provider
        return None

    def select_model(self, task_type: TaskType) -> str:
        """Select best model for task type."""
        return self.get_binding(task_type).model

    def get_provider_and_model(self, task_type: TaskType) -> tuple[str | None, str]:
        """Get both provider and model for task type."""
        binding = self.get_binding(task_type)
        provider = None
        if binding.provider in self._llm.list_providers():
            provider = binding.provider
        return provider, binding.model

    def get_fallback_chain(self, task_type: TaskType) -> list[ModelBinding]:
        """Get fallback chain for a task type based on its primary provider."""
        binding = self.get_binding(task_type)
        chain_key = self._determine_chain_key(task_type)
        chain = list(FALLBACK_CHAINS.get(chain_key, [binding]))
        # Ensure primary binding is first
        if binding not in chain:
            chain.insert(0, binding)
        return chain

    def _determine_chain_key(self, task_type: TaskType) -> str:
        """Select fallback chain based on task category."""
        binding = self.get_binding(task_type)

        # Code tasks → code_primary chain
        code_tasks = {
            TaskType.CODE_GENERATION,
            TaskType.CODE_DEBUGGING,
            TaskType.CODE_REVIEW,
            TaskType.CODE_TESTING,
        }
        if task_type in code_tasks:
            return "code_primary"

        # Math / architecture → reasoning chain
        if task_type in {TaskType.MATH_REASONING, TaskType.ARCHITECTURE_DESIGN}:
            return "reasoning"

        # If primary is ollama → ollama_primary chain
        if binding.provider == "ollama":
            return "ollama_primary"

        # Default → lmstudio_primary
        return "lmstudio_primary"

    def record_failure(self, model: str) -> None:
        """Record a model failure for circuit breaker logic."""
        self._failure_count[model] = self._failure_count.get(model, 0) + 1
        self._logger.warning("Model %s failure count: %d", model, self._failure_count[model])

    def record_success(self, model: str) -> None:
        """Record a successful call, reset failure count."""
        self._failure_count[model] = 0

    def should_skip(self, model: str, threshold: int = 3) -> bool:
        """Check if model should be skipped due to repeated failures."""
        return self._failure_count.get(model, 0) >= threshold

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all configured models."""
        return await self._llm.health()

    def list_bindings(self) -> dict[str, dict[str, Any]]:
        """List all task-to-model bindings."""
        return {
            tt.value: {"provider": b.provider, "model": b.model} for tt, b in self._task_map.items()
        }

    def set_binding(self, task_type: TaskType, binding: ModelBinding) -> None:
        """Override model binding for a task type."""
        self._task_map[task_type] = binding

    def reset_binding(self, task_type: TaskType) -> None:
        """Reset to default binding for task type."""
        if task_type in TASK_MODEL_MAP:
            self._task_map[task_type] = TASK_MODEL_MAP[task_type]
        else:
            self._task_map.pop(task_type, None)

    def get_status_summary(self) -> dict[str, Any]:
        """Get router status summary."""
        return {
            "providers": self._llm.list_providers(),
            "bindings": self.list_bindings(),
            "failure_counts": dict(self._failure_count),
            "active_chains": list(FALLBACK_CHAINS.keys()),
        }
