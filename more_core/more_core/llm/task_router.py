"""Task-aware model router with intelligent fallback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..core.types import TaskType
from .manager import ProviderModelPair as ModelBinding

if TYPE_CHECKING:
    from ..llm.manager import LLMManager

DEFAULT_LM_MODEL = "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"

TASK_MODEL_MAP: dict[TaskType, ModelBinding] = {
    TaskType.CODE_GENERATION: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.CODE_DEBUGGING: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.CODE_REVIEW: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.MATH_REASONING: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.DATA_ANALYSIS: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.NLP_TASK: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.ARCHITECTURE_DESIGN: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.MULTI_AGENT_ORCHESTRATION: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.SELF_IMPROVEMENT: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.CROSS_DOMAIN_TRANSFER: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
    TaskType.PLUGIN_DEFINED: ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
}

FALLBACK_BINDING = ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL)

FALLBACK_CHAINS: dict[str, list[ModelBinding]] = {
    "lmstudio_primary": [
        ModelBinding(provider="ollama", model=DEFAULT_OLLAMA_MODEL),
        ModelBinding(provider="lmstudio", model=DEFAULT_LM_MODEL),
    ],
    "ollama_fallback": [
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
        """Get fallback chain for a task type."""
        binding = self.get_binding(task_type)
        chain_key = self._determine_chain_key(task_type)
        chain = list(FALLBACK_CHAINS.get(chain_key, [binding]))
        if binding not in chain:
            chain.insert(0, binding)
        return chain

    def _determine_chain_key(self, task_type: TaskType) -> str:
        """Determine which fallback chain to use based on task type.

        All task types currently use the primary chain; custom chains
        can be registered via :meth:`DynamicModelRouter.set_custom_fallback_chain`.
        """
        return "lmstudio_primary"

    def record_failure(self, model: str) -> None:
        """Record a model failure for circuit breaker logic."""
        self._failure_count[model] = self._failure_count.get(model, 0) + 1
        self._logger.warning(f"Model {model} failure count: {self._failure_count[model]}")

    def record_success(self, model: str) -> None:
        """Record a successful call, reset failure count."""
        self._failure_count[model] = 0

    def should_skip(self, model: str, threshold: int = 3) -> bool:
        """Check if model should be skipped due to repeated failures."""
        return self._failure_count.get(model, 0) >= threshold

    async def health_check_all(self) -> dict[str, bool]:
        """Check health of all configured models."""
        return await self._llm.health()

    def list_bindings(self) -> dict[str, dict]:
        """List all task-to-model bindings."""
        return {
            tt.value: {"provider": b.provider, "model": b.model}
            for tt, b in self._task_map.items()
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

    def get_status_summary(self) -> dict:
        """Get router status summary."""
        return {
            "providers": self._llm.list_providers(),
            "bindings": self.list_bindings(),
            "failure_counts": dict(self._failure_count),
            "active_chains": list(FALLBACK_CHAINS.keys()),
        }