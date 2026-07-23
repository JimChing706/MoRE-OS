"""Reasoning Model Routing — special handling for thinking/reasoning models.

Reference: OpenFang v0.6.3 reasoning model support.
Detects reasoning-capable models and routes complex tasks to them
with appropriate budget_tokens and thinking parameters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


# Known reasoning model patterns
_REASONING_PATTERNS = [
    re.compile(r"o[1-4](-mini|-preview)?", re.IGNORECASE),  # OpenAI o1/o3/o4
    re.compile(r"claude.*thinking", re.IGNORECASE),  # Claude with thinking
    re.compile(r"deepseek.*reasoner", re.IGNORECASE),  # DeepSeek Reasoner
    re.compile(r"qwq", re.IGNORECASE),  # Qwen QwQ
    re.compile(r"gemini.*thinking", re.IGNORECASE),  # Gemini thinking
    re.compile(r".*-r1", re.IGNORECASE),  # DeepSeek R1
    re.compile(r"marco-o1", re.IGNORECASE),  # Marco-o1
]

# Models that support extended thinking budget
_BUDGET_MODELS = {
    "o1",
    "o1-preview",
    "o1-mini",
    "o3",
    "o3-mini",
    "o4-mini",
    "claude-sonnet-4-20250514",
    "deepseek-reasoner",
    "qwq-32b",
}


@dataclass
class ReasoningConfig:
    """Configuration for reasoning model invocation."""

    # Whether to enable extended thinking
    enable_thinking: bool = True
    # Token budget for the thinking/reasoning phase
    budget_tokens: int = 8192
    # Maximum total output tokens (thinking + answer)
    max_output_tokens: int = 16384
    # Whether to stream thinking tokens
    stream_thinking: bool = False
    # Temperature override (reasoning models often work best at low temp)
    temperature_override: float | None = None


@dataclass
class ReasoningResult:
    """Result from a reasoning model call."""

    answer: str
    thinking: str | None = None
    thinking_tokens: int = 0
    answer_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    provider: str = ""


def is_reasoning_model(model_name: str) -> bool:
    """Check if a model name indicates a reasoning/thinking model."""
    for pattern in _REASONING_PATTERNS:
        if pattern.search(model_name):
            return True
    return model_name.lower() in _BUDGET_MODELS


def supports_budget_tokens(model_name: str) -> bool:
    """Check if model supports explicit thinking budget."""
    return model_name.lower() in _BUDGET_MODELS


def get_reasoning_params(
    model_name: str,
    config: ReasoningConfig | None = None,
) -> dict[str, Any]:
    """Get extra API parameters for reasoning model invocation.

    Returns params to merge into the API request body.
    """
    config = config or ReasoningConfig()
    params: dict[str, Any] = {}

    if not is_reasoning_model(model_name):
        return params

    # OpenAI o-series
    if re.match(r"o[1-4]", model_name, re.IGNORECASE):
        params["max_completion_tokens"] = config.max_output_tokens
        if supports_budget_tokens(model_name):
            params["reasoning"] = {"effort": "high"}

    # Claude with extended thinking
    elif "claude" in model_name.lower():
        if config.enable_thinking:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": config.budget_tokens,
            }
            params["max_tokens"] = config.max_output_tokens

    # DeepSeek Reasoner
    elif "deepseek" in model_name.lower() and (
        "reasoner" in model_name.lower() or "r1" in model_name.lower()
    ):
        params["max_tokens"] = config.max_output_tokens

    # QwQ
    elif "qwq" in model_name.lower():
        params["max_tokens"] = config.max_output_tokens
        params["enable_thinking"] = config.enable_thinking

    # Temperature override for reasoning
    if config.temperature_override is not None:
        params["temperature"] = config.temperature_override

    return params


class ReasoningRouter:
    """Routes tasks to reasoning models when complexity warrants it.

    Integrates with TaskModelRouter to automatically select reasoning
    models for high-complexity tasks.
    """

    def __init__(self) -> None:
        self._config = ReasoningConfig()
        self._usage_stats: dict[str, int] = {}

    @property
    def config(self) -> ReasoningConfig:
        return self._config

    def update_config(self, **kwargs: Any) -> None:
        """Update reasoning config dynamically."""
        for key, val in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, val)

    def should_use_reasoning(self, task_complexity: float, query_length: int) -> bool:
        """Determine if a task should use a reasoning model.

        Args:
            task_complexity: 0.0–1.0 estimated complexity
            query_length: character count of the query

        Returns:
            True if reasoning model is recommended
        """
        # Use reasoning for high-complexity tasks or long queries
        if task_complexity >= 0.7:
            return True
        if query_length > 2000 and task_complexity >= 0.5:
            return True
        return False

    def get_params_for_model(self, model_name: str) -> dict[str, Any]:
        """Get reasoning-specific params for a model."""
        return get_reasoning_params(model_name, self._config)

    def record_usage(self, model: str, thinking_tokens: int, answer_tokens: int) -> None:
        """Record reasoning model usage for monitoring."""
        self._usage_stats[model] = self._usage_stats.get(model, 0) + 1
        _log.debug(
            "Reasoning usage: %s (thinking=%d, answer=%d)", model, thinking_tokens, answer_tokens
        )

    def stats(self) -> dict[str, Any]:
        return {
            "config": {
                "enable_thinking": self._config.enable_thinking,
                "budget_tokens": self._config.budget_tokens,
                "max_output_tokens": self._config.max_output_tokens,
            },
            "usage": dict(self._usage_stats),
            "known_reasoning_models": list(_BUDGET_MODELS),
        }
