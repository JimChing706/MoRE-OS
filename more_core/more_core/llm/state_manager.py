"""LLM Call State Manager - Dynamic parameter adjustment for LLM calls."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger(__name__)


@dataclass
class LLMCallState:
    """Current state of LLM call parameters."""

    provider: str = "lmstudio"
    model: str = "local-model"
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout_s: int = 120
    retry_count: int = 3
    fallback_enabled: bool = True
    cache_enabled: bool = True
    streaming_enabled: bool = False
    lmstudio_endpoint: str = "http://localhost:1234/v1"
    lmstudio_context_length: int = 32768
    lmstudio_gpu_layers: int = -1
    lmstudio_threads: int = 0
    lmstudio_vram_fraction: float = 0.8


@dataclass
class LLMUsageStats:
    """LLM usage statistics."""

    total_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    provider_usage: dict[str, int] = field(default_factory=dict)
    last_request_time: float = 0.0
    avg_latency_ms: float = 0.0


class LLMStateManager:
    """Manages LLM call state with dynamic adjustment capability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = LLMCallState()
        self._default_state = LLMCallState()
        self._usage = LLMUsageStats()
        self._history: list[dict[str, Any]] = []
        self._max_history = 100
        self._callbacks: list[Callable[..., Any]] = []

    def get_state(self) -> LLMCallState:
        return self._state

    def get_usage(self) -> LLMUsageStats:
        return self._usage

    def update_state(self, **kwargs: Any) -> LLMCallState:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)

            self._history.append(
                {
                    "timestamp": time.time(),
                    "changes": kwargs,
                    "state": self._state.__dict__.copy(),
                }
            )
            if len(self._history) > self._max_history:
                self._history.pop(0)

            for callback in self._callbacks:
                try:
                    callback(self._state)
                except Exception:
                    _log.exception("LLM state change callback failed")

            return self._state

    def reset_state(self) -> LLMCallState:
        with self._lock:
            self._state = LLMCallState(
                provider=self._default_state.provider,
                model=self._default_state.model,
                temperature=self._default_state.temperature,
                max_tokens=self._default_state.max_tokens,
            )
            return self._state

    def register_callback(self, callback: Callable[..., Any]) -> None:
        self._callbacks.append(callback)

    def record_usage(
        self,
        provider: str,
        tokens: int,
        cost: float,
        latency_ms: float,
    ) -> None:
        self._usage.total_requests += 1
        self._usage.total_tokens += tokens
        self._usage.total_cost += cost
        self._usage.last_request_time = time.time()

        if provider not in self._usage.provider_usage:
            self._usage.provider_usage[provider] = 0
        self._usage.provider_usage[provider] += tokens

        total = self._usage.total_requests
        self._usage.avg_latency_ms = (self._usage.avg_latency_ms * (total - 1) + latency_ms) / total

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._history[-limit:]

    def get_providers_info(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "lmstudio",
                "type": "local",
                "cost_per_1k": 0.0,
                "avg_latency_ms": 150,
                "recommended_for": ["high_quality_local", "development", "testing"],
                "description": "LM Studio - 本地模型运行器,支持多种开源模型",
                "endpoint": "http://localhost:1234/v1",
                "supports_streaming": True,
                "supports_vision": True,
                "config_options": {
                    "context_length": "最大上下文长度 (默认32768)",
                    "gpu_layers": "GPU加速层数 (-1=自动)",
                    "threads": "CPU线程数 (0=自动)",
                    "vram_fraction": "VRAM使用比例 (0.0-1.0)",
                },
            },
            {
                "name": "ollama",
                "type": "local",
                "cost_per_1k": 0.0,
                "avg_latency_ms": 100,
                "recommended_for": ["simple_tasks", "development"],
                "description": "Ollama - 轻量级本地模型运行器",
                "endpoint": "http://localhost:11434",
                "supports_streaming": True,
                "supports_vision": False,
            },
            {
                "name": "deepseek",
                "type": "api",
                "cost_per_1k": 0.014,
                "avg_latency_ms": 500,
                "recommended_for": ["code_generation", "reasoning"],
                "description": "DeepSeek - 高性价比API服务",
            },
            {
                "name": "openai",
                "type": "api",
                "cost_per_1k": 0.03,
                "avg_latency_ms": 800,
                "recommended_for": ["complex_reasoning"],
                "description": "OpenAI GPT-4 - 业界领先模型",
            },
            {
                "name": "anthropic",
                "type": "api",
                "cost_per_1k": 0.075,
                "avg_latency_ms": 1000,
                "recommended_for": ["high_quality"],
                "description": "Anthropic Claude - 高质量对话",
            },
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_state": self._state.__dict__,
            "usage": {
                "total_requests": self._usage.total_requests,
                "total_tokens": self._usage.total_tokens,
                "total_cost": self._usage.total_cost,
                "provider_usage": self._usage.provider_usage,
                "avg_latency_ms": self._usage.avg_latency_ms,
            },
            "available_providers": self.get_providers_info(),
        }


_global_llm_state = LLMStateManager()


def get_llm_state_manager() -> LLMStateManager:
    return _global_llm_state
