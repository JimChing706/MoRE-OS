"""LLM Manager: multi-provider routing with intelligent fallback chains."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncIterator, cast

from ..core.config import LLMProviderConfig
from ..core.errors import LLMError
from .provider import LLMProvider, LLMRequest, LLMResponse
from .providers.ollama import OllamaProvider
from .providers.lmstudio import LMStudioProvider
from .providers.openai_compat import OpenAICompatProvider
from .providers.deepseek import DeepSeekProvider
from .providers.mock import MockProvider


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
        return cast(
            "LLMProvider",
            OllamaProvider(
                name=cfg.name, endpoint=cfg.endpoint, model=cfg.model, timeout=cfg.timeout_s
            ),
        )
    if cfg.provider == "lmstudio":
        return cast(
            "LLMProvider",
            LMStudioProvider(
                name=cfg.name,
                endpoint=cfg.endpoint,
                model=cfg.model,
                api_key=cfg.api_key,
                timeout=cfg.timeout_s,
            ),
        )
    if cfg.provider == "deepseek":
        return cast(
            "LLMProvider",
            DeepSeekProvider(
                name=cfg.name,
                endpoint=cfg.endpoint or "https://api.deepseek.com",
                model=cfg.model or "deepseek-chat",
                api_key=cfg.api_key or "",
                timeout=cfg.timeout_s,
            ),
        )
    if cfg.provider == "mock":
        return cast("LLMProvider", MockProvider())
    # All other providers use the OpenAI-compatible chat/completions API
    _OPENAI_COMPAT = {
        "openai",
        "anthropic",
        "custom",
        "azure",
        "google",
        "groq",
        "mistral",
        "cohere",
        "openrouter",
        "together",
        "xai",
        "sambanova",
        "fireworks",
        "perplexity",
        "cerebras",
        "huggingface",
        "replicate",
        "vllm",
    }
    if cfg.provider in _OPENAI_COMPAT:
        return cast(
            "LLMProvider",
            OpenAICompatProvider(
                name=cfg.name,
                endpoint=cfg.endpoint,
                model=cfg.model,
                api_key=cfg.api_key or "",
                timeout=cfg.timeout_s,
            ),
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
    """Routes an :class:`LLMRequest` through configured fallback chains.

    Reads :class:`LLMStateManager` at generate-time to apply runtime
    overrides (provider / model / temperature / max_tokens) set by the
    frontend or API — see :meth:`generate`.
    """

    def __init__(
        self,
        providers: list[LLMProviderConfig],
        fallback_chain: list[str] | None = None,
        state_manager: Any | None = None,
    ) -> None:
        self._providers: dict[str, LLMProvider] = {
            cfg.name: _build_provider(cfg) for cfg in providers
        }
        self._fallback = fallback_chain or list(self._providers)
        self._cache = _LRU()
        self._cache_lock = asyncio.Lock()
        self._failure_counts: dict[str, int] = {}
        self._state_manager = state_manager
        # Health check cache: provider -> (is_healthy, timestamp)
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._health_cache_ttl: float = 30.0

    async def _check_health_cached(self, name: str) -> bool:
        """Cached health check for a provider (TTL 30s)."""
        now = time.monotonic()
        if name in self._health_cache:
            healthy, ts = self._health_cache[name]
            if now - ts < self._health_cache_ttl:
                return healthy
        try:
            healthy = await self._providers[name].health()
        except Exception:
            healthy = False
        self._health_cache[name] = (healthy, now)
        return healthy

    def _apply_runtime_state(
        self, request: LLMRequest, provider: str | None
    ) -> tuple[str | None, LLMRequest]:
        """Merge LLMStateManager runtime overrides into the request."""
        sm = self._state_manager
        if sm is None:
            return provider, request
        state = sm.get_state()
        effective_provider = provider or state.provider
        if effective_provider != provider and effective_provider not in self._providers:
            effective_provider = provider
        effective_model = request.model_override or state.model
        t = state.temperature
        if t is not None:
            request.temperature = t
        mt = state.max_tokens
        if mt is not None:
            request.max_tokens = mt
        if effective_model != request.model_override:
            request = self._create_request_with_model(request, effective_model)
        return effective_provider, request

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

        provider, request = self._apply_runtime_state(request, provider)

        chain = [provider] if provider else list(self._fallback)
        last_exc: Exception | None = None

        for name in chain:
            if name not in self._providers:
                continue
            if self._should_skip(name, request.model_override):
                _logger.info("Skipping %s due to repeated failures", name)
                continue
            # Quick health check before attempting (cached, TTL 30s)
            if not await self._check_health_cached(name):
                _logger.warning("Provider %s is unhealthy, skipping", name)
                continue

            key = self._cache_key(request, name, request.model_override)
            if use_cache:
                async with self._cache_lock:
                    if key in self._cache:
                        cached = self._cache[key]
                        return LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                        )
            try:
                start = time.perf_counter()
                resp = await self._providers[name].generate(request)
                resp.latency_ms = (time.perf_counter() - start) * 1000
                self._record_success(name, request.model_override)
                if use_cache:
                    async with self._cache_lock:
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
                _logger.info("Skipping %s/%s due to failures", pair.provider, pair.model)
                continue
            if not await self._check_health_cached(pair.provider):
                _logger.warning("Provider %s is unhealthy, skipping", pair.provider)
                continue

            req = self._create_request_with_model(request, pair.model)
            key = self._cache_key(req, pair.provider, pair.model)

            if use_cache:
                async with self._cache_lock:
                    if key in self._cache:
                        cached = self._cache[key]
                        return LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                        )

            try:
                start = time.perf_counter()
                resp = await self._providers[pair.provider].generate(req)
                resp.latency_ms = (time.perf_counter() - start) * 1000
                self._record_success(pair.provider, pair.model)
                if use_cache:
                    async with self._cache_lock:
                        self._cache.put(key, resp)
                return resp
            except Exception as exc:
                self._record_failure(pair.provider, pair.model)
                last_exc = exc
                _logger.warning(f"{pair.provider}/{pair.model} failed: {exc}")
                continue

        raise LLMError(f"all fallback pairs failed: {last_exc}") from last_exc

    async def generate_parallel(
        self,
        request: LLMRequest,
        candidates: list[ProviderModelPair],
        use_cache: bool = True,
        timeout_s: float = 120.0,
    ) -> LLMResponse:
        """Race-to-first: send request to multiple providers simultaneously.

        All candidates are tried *in parallel*.  The first successful
        response wins; the remaining in-flight requests are cancelled.

        This is the key enabler for parallel-LLM architectures:
        - 2× 27B models on the same LM Studio instance → load balanced
        - LM Studio 27B + Ollama 7B → fast local fallback
        - LM Studio + DeepSeek cloud API → hybrid acceleration

        Args:
            request: LLM request
            candidates: List of (provider, model) pairs to race
            use_cache: Whether to check the LRU cache first
            timeout_s: Max wall-clock time before raising

        Returns:
            First successful LLMResponse

        Raises:
            LLMError: When all candidates fail
        """
        import asyncio as _aio

        # 1. Filter to healthy, non-skipped candidates
        valid: list[tuple[ProviderModelPair, str]] = []  # (pair, cache_key)
        for pair in candidates:
            if pair.provider not in self._providers:
                continue
            if self._should_skip(pair.provider, pair.model):
                _logger.info(
                    "generate_parallel: skipping %s/%s (failures)", pair.provider, pair.model
                )
                continue
            if not await self._check_health_cached(pair.provider):
                _logger.warning("generate_parallel: skipping %s (unhealthy)", pair.provider)
                continue
            req = self._create_request_with_model(request, pair.model)
            cache_key = self._cache_key(req, pair.provider, pair.model)
            valid.append((pair, cache_key))

        if not valid:
            raise LLMError("generate_parallel: no healthy candidates")

        # 2. Cache hit → return immediately (no race needed)
        if use_cache:
            async with self._cache_lock:
                for pair, cache_key in valid:
                    if cache_key in self._cache:
                        cached = self._cache[cache_key]
                        _logger.debug(
                            "generate_parallel: cache hit %s/%s", pair.provider, pair.model
                        )
                        return LLMResponse(
                            content=cached.content,
                            provider=cached.provider,
                            model=cached.model,
                            prompt_tokens=cached.prompt_tokens,
                            completion_tokens=cached.completion_tokens,
                            latency_ms=0.0,
                            cached=True,
                        )

        # 3. Launch all in parallel, race to first success
        async def _try_one(pair: ProviderModelPair) -> LLMResponse:
            """Attempt one candidate.  Raises on failure."""
            req = self._create_request_with_model(request, pair.model)
            start = time.perf_counter()
            resp = await self._providers[pair.provider].generate(req)
            resp.latency_ms = (time.perf_counter() - start) * 1000
            return resp

        tasks = {_aio.create_task(_try_one(p)): p for p, _ in valid}
        pending: set[_aio.Task[Any]] = set(tasks)
        errors: list[tuple[str, str, str]] = []

        try:
            done, pending = await _aio.wait(
                pending,
                timeout=timeout_s,
                return_when=_aio.FIRST_COMPLETED,
            )

            for task in done:
                pair = tasks[task]
                try:
                    resp: LLMResponse = task.result()
                    # Success!  Cache it and return.
                    self._record_success(pair.provider, pair.model)
                    if use_cache:
                        key = self._cache_key(
                            self._create_request_with_model(request, pair.model),
                            pair.provider,
                            pair.model,
                        )
                        async with self._cache_lock:
                            self._cache.put(key, resp)
                    _logger.info(
                        "generate_parallel: won race [%s/%s] in %.0fms",
                        pair.provider,
                        pair.model,
                        resp.latency_ms,
                    )
                    # Cancel remaining tasks
                    for t in pending:
                        t.cancel()
                    return resp
                except Exception as exc:
                    self._record_failure(pair.provider, pair.model)
                    errors.append((pair.provider, pair.model, str(exc)))
                    _logger.warning(
                        "generate_parallel: %s/%s failed: %s",
                        pair.provider,
                        pair.model,
                        exc,
                    )

            # If we get here, first-completed tasks all failed.
            # We still have pending tasks — wait for them.
            if pending:
                _logger.debug(
                    "generate_parallel: first batch failed, waiting for %d remaining", len(pending)
                )
                try:
                    done2, pending = await _aio.wait(
                        pending,
                        timeout=_aio.get_running_loop().time() if False else timeout_s - 10,
                        return_when=_aio.FIRST_COMPLETED,
                    )
                    for task in done2:
                        pair = tasks[task]
                        try:
                            resp = task.result()
                            self._record_success(pair.provider, pair.model)
                            if use_cache:
                                key = self._cache_key(
                                    self._create_request_with_model(request, pair.model),
                                    pair.provider,
                                    pair.model,
                                )
                                async with self._cache_lock:
                                    self._cache.put(key, resp)
                            _logger.info(
                                "generate_parallel: won race (later) [%s/%s]",
                                pair.provider,
                                pair.model,
                            )
                            for t in pending:
                                t.cancel()
                            return resp
                        except Exception as exc:
                            self._record_failure(pair.provider, pair.model)
                            errors.append((pair.provider, pair.model, str(exc)))
                except Exception:
                    pass

            # All failed
            for t in pending:
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

        except _aio.TimeoutError:
            for t in pending:
                t.cancel()
            raise LLMError(
                f"generate_parallel: timeout after {timeout_s}s with {len(errors)} failures"
            )

        err_summary = "; ".join(f"{p}/{m}: {e[:80]}" for p, m, e in errors[:5])
        raise LLMError(
            f"generate_parallel: all {len(candidates)} candidates failed. Errors: {err_summary}"
        )

    async def stream(
        self,
        request: LLMRequest,
        provider: str | None = None,
        model_override: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the best available provider with fallback."""
        chain = [provider] if provider else list(self._fallback)
        for name in chain:
            if name not in self._providers or self._should_skip(name, model_override):
                continue
            try:
                async for token in await self._providers[name].stream(request):
                    yield token
                self._record_success(name, model_override)
                return
            except Exception as exc:
                self._record_failure(name, model_override)
                _logger.warning(f"Stream from {name} failed: {exc}")
                continue
        raise LLMError("all providers failed streaming")

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
                except Exception as exc:
                    _logger.warning("Error closing provider: %s", exc)
