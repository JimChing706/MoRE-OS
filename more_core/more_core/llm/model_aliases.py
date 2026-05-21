"""Model Aliases — convenient shortcuts and free model discovery.

Reference: OpenFang v0.6.4 OpenRouter free model aliases.
Maps friendly names to full provider/model identifiers.
Includes free-tier model aliases for zero-cost development.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelAlias:
    """A model alias mapping."""
    alias: str
    provider: str
    model: str
    description: str = ""
    free: bool = False
    context_length: int = 0
    capabilities: list[str] | None = None


# OpenRouter free models (verified tool-capable, OpenFang v0.6.4)
FREE_MODELS: list[ModelAlias] = [
    ModelAlias(
        alias="free-coder",
        provider="openrouter",
        model="qwen/qwen3-coder:free",
        description="Qwen3 Coder (free) — code generation",
        free=True, context_length=32768, capabilities=["code", "chat"],
    ),
    ModelAlias(
        alias="free-large",
        provider="openrouter",
        model="openrouter/free-large",
        description="Best available free large model",
        free=True, context_length=128000, capabilities=["chat", "reasoning"],
    ),
    ModelAlias(
        alias="free-llama",
        provider="openrouter",
        model="meta-llama/llama-3.3-70b-instruct:free",
        description="Llama 3.3 70B Instruct (free)",
        free=True, context_length=131072, capabilities=["chat", "code", "tools"],
    ),
    ModelAlias(
        alias="free-glm",
        provider="openrouter",
        model="thudm/glm-4.5-air:free",
        description="GLM 4.5 Air (free) — multilingual",
        free=True, context_length=32768, capabilities=["chat", "multilingual"],
    ),
    ModelAlias(
        alias="free-gpt",
        provider="openrouter",
        model="openrouter/gpt-oss-120b:free",
        description="GPT-OSS 120B (free) — large general",
        free=True, context_length=65536, capabilities=["chat", "reasoning"],
    ),
]

# Standard model aliases
STANDARD_ALIASES: list[ModelAlias] = [
    # Fast models
    ModelAlias(alias="fast", provider="groq", model="llama-3.3-70b-versatile",
              description="Fastest inference (Groq)", context_length=131072),
    ModelAlias(alias="fast-small", provider="groq", model="llama-3.1-8b-instant",
              description="Fast small model (Groq)", context_length=131072),
    # Reasoning models
    ModelAlias(alias="reasoning", provider="openai", model="o4-mini",
              description="Best reasoning (OpenAI o4-mini)", capabilities=["reasoning"]),
    ModelAlias(alias="deep-think", provider="deepseek", model="deepseek-reasoner",
              description="DeepSeek Reasoner (R1)", capabilities=["reasoning"]),
    # Coding models
    ModelAlias(alias="coder", provider="anthropic", model="claude-sonnet-4-20250514",
              description="Best coding model", capabilities=["code", "tools"]),
    ModelAlias(alias="coder-local", provider="lmstudio", model="gemma-4-coder",
              description="Local coding model", capabilities=["code"]),
    # Large context
    ModelAlias(alias="long-context", provider="google", model="gemini-2.0-flash",
              description="1M context (Gemini)", context_length=1000000),
    # Multilingual
    ModelAlias(alias="multilingual", provider="openai", model="gpt-4o",
              description="Best multilingual", capabilities=["multilingual", "vision"]),
]


class ModelAliasRegistry:
    """Registry for model aliases with resolution."""

    def __init__(self) -> None:
        self._aliases: dict[str, ModelAlias] = {}
        # Register defaults
        for alias in FREE_MODELS + STANDARD_ALIASES:
            self._aliases[alias.alias] = alias

    def register(self, alias: ModelAlias) -> None:
        self._aliases[alias.alias] = alias

    def unregister(self, alias_name: str) -> None:
        self._aliases.pop(alias_name, None)

    def resolve(self, name: str) -> ModelAlias | None:
        """Resolve an alias to provider/model pair."""
        return self._aliases.get(name)

    def list_aliases(self, free_only: bool = False) -> list[ModelAlias]:
        """List all registered aliases."""
        aliases = list(self._aliases.values())
        if free_only:
            aliases = [a for a in aliases if a.free]
        return sorted(aliases, key=lambda a: a.alias)

    def list_free(self) -> list[ModelAlias]:
        """List only free models."""
        return self.list_aliases(free_only=True)

    def to_api_dict(self, free_only: bool = False) -> list[dict[str, Any]]:
        return [
            {
                "alias": a.alias,
                "provider": a.provider,
                "model": a.model,
                "description": a.description,
                "free": a.free,
                "context_length": a.context_length,
                "capabilities": a.capabilities or [],
            }
            for a in self.list_aliases(free_only)
        ]

    def stats(self) -> dict[str, Any]:
        free = [a for a in self._aliases.values() if a.free]
        return {
            "total_aliases": len(self._aliases),
            "free_models": len(free),
            "providers": list({a.provider for a in self._aliases.values()}),
        }
