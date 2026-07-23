"""Dynamic model router — env-driven, alias-aware, reasoning-integrated."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from ..core.types import TaskType
from .model_aliases import ModelAliasRegistry
from .reasoning import ReasoningRouter
from .task_router import FALLBACK_CHAINS, TaskModelRouter
from .manager import ProviderModelPair as ModelBinding

if TYPE_CHECKING:
    from ..llm.manager import LLMManager

_log = logging.getLogger(__name__)

_ENV_PREFIX = "MORE_TASK_MODEL_"


def _load_env_overrides() -> dict[TaskType, ModelBinding]:
    """Load task→model overrides from environment variables.

    Format: ``MORE_TASK_MODEL_<TASK_TYPE>=<provider>:<model>``
    Example: ``MORE_TASK_MODEL_CODE_GENERATION=ollama:qwen2.5:7b``
    """
    overrides: dict[TaskType, ModelBinding] = {}
    for key, val in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        task_name = key[len(_ENV_PREFIX) :].lower()
        try:
            task_type = TaskType(task_name)
        except ValueError:
            _log.warning("unknown task type in env: %s", key)
            continue
        parts = val.split(":", 1)
        if len(parts) != 2:
            _log.warning("invalid format for %s (expected provider:model)", key)
            continue
        overrides[task_type] = ModelBinding(provider=parts[0], model=parts[1])
        _log.info("env override: %s → %s/%s", task_type.value, parts[0], parts[1])
    return overrides


class DynamicModelRouter(TaskModelRouter):
    """Extends :class:`TaskModelRouter` with alias resolution, reasoning
    awareness, and runtime-configurable overrides via env vars or API calls.
    """

    def __init__(self, llm_manager: LLMManager) -> None:
        super().__init__(llm_manager)
        self._alias_registry = ModelAliasRegistry()
        self._reasoning_router = ReasoningRouter()
        self._custom_fallback_chains: dict[str, list[ModelBinding]] = {}

        # Apply env overrides
        for tt, binding in _load_env_overrides().items():
            self._task_map[tt] = binding

    # -- properties ----------------------------------------------------------

    @property
    def alias_registry(self) -> ModelAliasRegistry:
        return self._alias_registry

    @property
    def reasoning_router(self) -> ReasoningRouter:
        return self._reasoning_router

    # -- alias-aware resolution ---------------------------------------------

    def resolve_alias(self, name: str) -> ModelBinding | None:
        """Resolve a model alias (e.g. ``free-coder``) to a binding.

        Returns ``None`` if the alias is unknown.
        """
        alias = self._alias_registry.resolve(name)
        if alias is None:
            return None
        return ModelBinding(provider=alias.provider, model=alias.model)

    def get_binding(self, task_type: TaskType) -> ModelBinding:
        binding = super().get_binding(task_type)
        # Reasoning is opt-in: callers must pass actual difficulty/complexity.
        # The default binding does NOT auto-route to reasoning models.
        if self._reasoning_router.should_use_reasoning(0.0, 0):
            alias = self._alias_registry.resolve("reasoning")
            if alias is not None:
                return ModelBinding(provider=alias.provider, model=alias.model)
        return binding

    def get_fallback_chain(self, task_type: TaskType) -> list[ModelBinding]:
        chain_key = self._determine_chain_key(task_type)
        if chain_key in self._custom_fallback_chains:
            return list(self._custom_fallback_chains[chain_key])
        return super().get_fallback_chain(task_type)

    # -- runtime configuration API ------------------------------------------

    def set_custom_fallback_chain(self, name: str, chain: list[ModelBinding]) -> None:
        """Register or update a named fallback chain."""
        self._custom_fallback_chains[name] = list(chain)
        _log.info("custom fallback chain '%s' set with %d pairs", name, len(chain))

    def remove_custom_fallback_chain(self, name: str) -> None:
        self._custom_fallback_chains.pop(name, None)

    def get_routing_config(self) -> dict[str, Any]:
        """Full routing configuration, suitable for API serialization."""
        return {
            "bindings": self.list_bindings(),
            "fallback_chains": {
                k: [{"provider": p, "model": p.model} for p in v if hasattr(p, "provider")]
                for k, v in {**FALLBACK_CHAINS, **self._custom_fallback_chains}.items()
            },
            "aliases": self._alias_registry.to_api_dict(),
            "reasoning": self._reasoning_router.stats(),
            "failure_counts": dict(self._failure_count),
            "providers": self._llm.list_providers(),
        }

    def update_task_binding(self, task_type: TaskType, provider: str, model: str) -> None:
        """Set a custom binding for a task type.  Accepts alias in *model*."""
        resolved = self.resolve_alias(model) or ModelBinding(provider=provider, model=model)
        self.set_binding(task_type, resolved)

    def update_fallback_chain(self, name: str, chain: list[dict[str, str]]) -> None:
        """Set a fallback chain from API-friendly dict list."""
        pairs = [ModelBinding(provider=p["provider"], model=p["model"]) for p in chain]
        self.set_custom_fallback_chain(name, pairs)

    def get_llm_kwargs(self, task_type: TaskType) -> dict[str, Any]:
        """Build extra kwargs for :meth:`LLMManager.generate`."""
        return self.get_llm_kwargs_with_difficulty(task_type, 0)

    def get_llm_kwargs_with_difficulty(
        self, task_type: TaskType, difficulty: int
    ) -> dict[str, Any]:
        """Build extra kwargs with actual difficulty for reasoning routing."""
        binding = self.get_binding(task_type)
        extra: dict[str, Any] = {
            "provider": binding.provider,
            "model_override": binding.model,
        }
        if self._reasoning_router.should_use_reasoning(difficulty / 10.0, 0):
            extra["extra_params"] = self._reasoning_router.get_params_for_model(binding.model)
        return extra

    def select_provider(self, task_type: TaskType, difficulty: int | None = None) -> str | None:
        """Select best provider, optionally considering task difficulty."""
        binding = self.get_binding(task_type)
        if difficulty is not None:
            complexity = difficulty / 10.0
            if self._reasoning_router.should_use_reasoning(complexity, 0):
                alias = self._alias_registry.resolve("reasoning")
                if alias is not None:
                    return alias.provider if alias.provider in self._llm.list_providers() else None
        if binding.provider in self._llm.list_providers():
            return binding.provider
        return None

    def select_model(self, task_type: TaskType, difficulty: int | None = None) -> str:
        """Select best model, optionally considering task difficulty."""
        if difficulty is not None:
            complexity = difficulty / 10.0
            if self._reasoning_router.should_use_reasoning(complexity, 0):
                alias = self._alias_registry.resolve("reasoning")
                if alias is not None:
                    return alias.model
        return self.get_binding(task_type).model
