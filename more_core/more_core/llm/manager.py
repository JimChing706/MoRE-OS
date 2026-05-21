"""LLM Manager: multi-provider routing with intelligent fallback chains."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

from ..core.config import LLMProviderConfig
from ..core.errors import LLMError
from .provider import LLMProvider, LLMRequest, LLMResponse
from .providers.ollama import OllamaProvider
from .providers.lmstudio import LMStudioProvider
from .providers.openai_compat import OpenAICompatProvider
from .providers.deepseek import DeepSeekProvider


_CACHE_MAX = 256

_logger = logging.getLogger("more_core.llm_manager")


class _LRU(OrderedDict[str, LLMResponse]):
    def put(self, key: str, value: LLMResponse) -> None:
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > _CACHE_MAX:
            self.popitem(last=False)


def _build_provider(cfg: LLMProviderConfig) -> LLMProvider:
    if cfg.provider == "ollama":
        return OllamaProvider(name=cfg.name, endpoint=cfg.endpoint, model=cfg.model, timeout=cfg.timeout_s)
    if cfg.provider == "lmstudio":
        return LMStudioProvider(
            name=cfg.name, endpoint=cfg.endpoint, model=cfg.model,
            api_key=cfg.api_key, timeout=cfg.timeout_s,
        )
    if cfg.provider == "deepseek":
        return DeepSeekProvider(
            name=cfg.name, endpoint=cfg.endpoint or "https://api.deepseek.com",
            model=cfg.model or "deepseek-chat",
            api_key=cfg.api_key or "",
            timeout=cfg.timeout_s,
        )
    # All other providers use the OpenAI-compatible chat/completions API
    _OPENAI_COMPAT = {
        "openai", "anthropic", "custom", "azure", "google", "groq",
        "mistral", "cohere", "openrouter", "together", "xai",
        "sambanova", "fireworks", "perplexity", "cerebras",
        "huggingface", "replicate", "vllm",
    }
    if cfg.provider in _OPENAI_COMPAT:
        return OpenAICompatProvider(
            name=cfg.name, endpoint=cfg.endpoint, model=cfg.model,
            api_key=cfg.api_key or "", timeout=cfg.timeout_s,
        )
    raise LLMError(f"unsupported provider: {cfg.provider}")


@dataclass
class ProviderModelPair:
    """A provider and model pair for fallback chains."""
    provider: str
    model: str


@dataclass
class FallbackChain:
    """A complete fallback chain with multiple provider-model pairs."""
    pairs: list[ProviderModelPair]


class LLMManager:
    """Routes an :class:`LLMRequest` through configured fallback chains."""

    def __init__(
        self,
        providers: list[LLMProviderConfig],
        fallback_chain: list[str] | None = None,
    ) -> None:
        self._providers: dict[str, LLMProvider] = {
            cfg.name: _build_provider(cfg) for cfg in providers
        }
        self._fallback = fallback_chain or list(self._providers)
        self._cache = _LRU()
        self._failure_counts: dict[str, int] = {}

    def list_providers(self) -> list[str]:
        return list(self._providers)

    @staticmethod
    def _cache_key(req: LLMRequest, provider: str, model: str | None = None) -> str:
        raw = (
            f"{provider}|{model or ''}|{req.system or ''}|{req.prompt}|{req.temperature}"
            f"|{req.max_tokens}|{','.join(req.stop)}|{sorted(req.extra.items())}"
            f"|{req.model_override or ''}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _create_request_with_model(self, request: LLMRequest, model: str | None) -> LLMRequest:
        """Create a new request with model override if provided."""
        if model:
            return LLMRequest(
                prompt=request.prompt,
                system=request.system,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stop=list(request.stop),
                extra=dict(request.extra),
                model_override=model,
            )
        return request

    def _should_skip(self, provider: str, model: str | None, threshold: int = 3) -> bool:
        """Check if provider/model should be skipped due to failures."""
        key = f"{provider}:{model or 'default'}"
        return self._failure_counts.get(key, 0) >= threshold

    def _record_failure(self, provider: str, model: str | None) -> None:
        """Record a failure for a provider/model pair."""
        key = f"{provider}:{model or 'default'}"
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
        _logger.warning(f"Failure recorded for {key}: {self._failure_counts[key]}")

    def _record_success(self, provider: str, model: str | None) -> None:
        """Record a success, reset failure count."""
        key = f"{provider}:{model or 'default'}"
        self._failure_counts[key] = 0

    async def generate(
        self,
        request: LLMRequest,
        provider: str | None = None,
        model_override: str | None = None,
        use_cache: bool = True,
    ) -> LLMResponse:
        """Generate LLM response with fallback chain.

        Args:
            request: LLM request with prompt, temperature, etc.
            provider: Specific provider to use, or None for fallback chain
            model_override: Override model name for this request
            use_cache: Whether to use response caching

        Returns:
            LLMResponse with generated content

        Raises:
            LLMError: When all providers in fallback chain fail
        """
        if model_override:
            request = self._create_request_with_model(request, model_override)
            provider = provider or self._fallback[0] if self._fallback else None

        chain = [provider] if provider else list(self._fallback)
        last_exc: Exception | None = None

        for name in chain:
            if name not in self._providers:
                continue
            if self._should_skip(name, request.model_override):
                _logger.info(f"Skipping {name} due to repeated failures")
                continue

            key = self._cache_key(request, name, request.model_override)
            if use_cache and key in self._cache:
                cached = self._cache[key]
                return LLMResponse(
                    content=cached.content, provider=cached.provider, model=cached.model,
                    prompt_tokens=cached.prompt_tokens, completion_tokens=cached.completion_tokens,
                    latency_ms=0.0, cached=True,
                )
            try:
                start = time.perf_counter()
                resp = await self._providers[name].generate(request)
                resp.latency_ms = (time.perf_counter() - start) * 1000
                self._record_success(name, request.model_override)
                if use_cache:
                    self._cache.put(key, resp)
                return resp
            except Exception as exc:
                self._record_failure(name, request.model_override)
                last_exc = exc
                _logger.warning(f"Provider {name} failed: {exc}")
                continue
        raise LLMError(f"all providers failed: {last_exc}") from last_exc

    async def generate_with_fallback_chain(
        self,
        request: LLMRequest,
        chain: list[ProviderModelPair],
        use_cache: bool = True,
    ) -> LLMResponse:
        """Generate with a complete fallback chain of provider-model pairs.

        Args:
            request: LLM request
            chain: List of (provider, model) pairs to try in order
            use_cache: Whether to use response caching

        Returns:
            LLMResponse from first successful pair

        Raises:
            LLMError: When all pairs in chain fail
        """
        last_exc: Exception | None = None

        for pair in chain:
            if pair.provider not in self._providers:
                continue
            if self._should_skip(pair.provider, pair.model):
                _logger.info(f"Skipping {pair.provider}/{pair.model} due to failures")
                continue

            req = self._create_request_with_model(request, pair.model)
            key = self._cache_key(req, pair.provider, pair.model)

            if use_cache and key in self._cache:
                cached = self._cache[key]
                return LLMResponse(
                    content=cached.content, provider=cached.provider, model=cached.model,
                    prompt_tokens=cached.prompt_tokens, completion_tokens=cached.completion_tokens,
                    latency_ms=0.0, cached=True,
                )

            try:
                start = time.perf_counter()
                resp = await self._providers[pair.provider].generate(req)
                resp.latency_ms = (time.perf_counter() - start) * 1000
                self._record_success(pair.provider, pair.model)
                if use_cache:
                    self._cache.put(key, resp)
                return resp
            except Exception as exc:
                self._record_failure(pair.provider, pair.model)
                last_exc = exc
                _logger.warning(f"{pair.provider}/{pair.model} failed: {exc}")
                continue

        raise LLMError(f"all fallback pairs failed: {last_exc}") from last_exc

    async def health(self) -> dict[str, bool]:
        """Check health status of all providers."""
        return {name: await p.health() for name, p in self._providers.items()}

    def get_failure_counts(self) -> dict[str, int]:
        """Get failure counts for monitoring."""
        return dict(self._failure_counts)

    def reset_failure_counts(self) -> None:
        """Reset all failure counts (e.g., after system recovery)."""
        self._failure_counts.clear()
        _logger.info("All failure counts reset")

    async def close(self) -> None:
        """Close all provider connection pools for graceful shutdown."""
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception:
                    pass