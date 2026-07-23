"""Task-aware model router with intelligent fallback.

Routes different task types to appropriate models:
- Simple tasks (NLP, data analysis) → Ollama qwen2.5:7b (fast, cheap)
- Complex tasks (code generation, architecture) → LM Studio large model (capable)
- Math reasoning → LM Studio reasoning model
- Self-improvement / orchestration → LM Studio large model
"""

from __future__ import annotations

import logging
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

# Model identifiers — 27B family (fast load, strong reasoning, parallel-friendly)
DEFAULT_LM_MODEL = "qwen/qwen3.6-27b"  # 通用主力
DEFAULT_LM_REASONING_MODEL = "qwen3.5-27b-claude-4.6-opus-reasoning-distilled-v2"  # 推理增强
DEFAULT_LM_CODER_MODEL = "gemma-4-coder"  # 代码专用
DEFAULT_LM_FALLBACK_MODEL = "qwen3.5-27b-claude-4.6-opus-reasoning-distilled"  # 并行备选
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_UNCENSORED = "aratan/qwen3.5-uncensored:9b"

# ── Task-to-model routing ────────────────────────────────────────────────
# 并行优势策略：
#   - 简单任务 → ollama 7B（极快，<1s 首 token）
#   - 代码任务 → lmstudio coder + 标准模型 race-to-first
#   - 推理任务 → lmstudio reasoning 增强版
#   - 关键路径可同时调用多个 27B 变体，取最快结果

TASK_MODEL_MAP: dict[TaskType, ModelBinding] = {
    # 代码任务 → coder 变体（26B MoE，代码专项训练）
    TaskType.CODE_GENERATION: ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
    TaskType.CODE_DEBUGGING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CODE_REVIEW: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CODE_TESTING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
    # 数学/架构 → 推理增强版 27B
    TaskType.MATH_REASONING: ModelBinding(provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL),
    TaskType.ARCHITECTURE_DESIGN: ModelBinding(
        provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL
    ),
    # 简单任务 → Ollama 7B（毫秒级首 token）
    TaskType.NLP_TASK: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.DATA_ANALYSIS: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    # 编排/元任务 → 通用 27B
    TaskType.MULTI_AGENT_ORCHESTRATION: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.SELF_IMPROVEMENT: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.CROSS_DOMAIN_TRANSFER: ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    TaskType.PLUGIN_DEFINED: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
}

FALLBACK_BINDING = ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL)

# ── Fallback chains ──────────────────────────────────────────────────────
# When primary model fails, try alternatives in order.

FALLBACK_CHAINS: dict[str, list[ModelBinding]] = {
    # LM Studio 多 27B 并行 → Ollama 兜底
    "lmstudio_primary": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_FALLBACK_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_UNCENSORED),
    ],
    # Ollama 优先 → LM Studio 备选
    "ollama_primary": [
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_UNCENSORED),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
    ],
    # 推理任务 → reasoning 增强版优先
    "reasoning": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_REASONING_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_FALLBACK_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    ],
    # 代码任务 → coder + 通用 27B race
    "code_primary": [
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_CODER_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_FALLBACK_MODEL),
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    ],
}


class TaskModelRouter:
    """Routes task types to specialized models with intelligent fallback."""

    def __init__(self, llm_manager: "LLMManager") -> None:
        self._llm = llm_manager
        self._task_map = dict(TASK_MODEL_MAP)
        self._logger = logging.getLogger("more_core.task_router")
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
