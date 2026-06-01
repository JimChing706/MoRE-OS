"""LLM provider contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass(slots=True)
class LLMRequest:
    prompt: str
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024
    stop: list[str] = field(default_factory=list)
    extra: dict[str, object] = field(default_factory=dict)
    model_override: str | None = None
    enable_thinking: bool = False  # DeepSeek V4 thinking tokens


@dataclass(slots=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    reasoning_content: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]: ...

    async def health(self) -> bool: ...
