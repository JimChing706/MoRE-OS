"""Tests for LLMManager multi-provider fallback and caching."""

from __future__ import annotations

import pytest

from more_core.core.errors import LLMError
from more_core.llm.manager import LLMManager, _LRU
from more_core.llm.provider import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _GoodProvider:
    def __init__(self, name: str = "good") -> None:
        self.name = name
        self.model = "test-model"
        self.called = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.called += 1
        return LLMResponse(
            content=f"reply from {self.name}",
            provider=self.name,
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
        )

    async def health(self) -> bool:
        return True


class _BadProvider:
    def __init__(self, name: str = "bad") -> None:
        self.name = name
        self.model = "fail-model"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMError(f"{self.name} is down")

    async def health(self) -> bool:
        return False


def _manager_with_providers(providers, fallback=None) -> LLMManager:
    mgr = LLMManager(providers=[], fallback_chain=[])
    mgr._providers = {p.name: p for p in providers}
    mgr._fallback = fallback or list(mgr._providers)
    return mgr


# ---------------------------------------------------------------------------
# Fallback chain tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_provider_success() -> None:
    good = _GoodProvider()
    mgr = _manager_with_providers([good])
    resp = await mgr.generate(LLMRequest(prompt="hi"), use_cache=False)
    assert resp.content == "reply from good"
    assert good.called == 1


@pytest.mark.asyncio
async def test_fallback_skips_failing_provider() -> None:
    bad = _BadProvider("primary")
    good = _GoodProvider("secondary")
    mgr = _manager_with_providers([bad, good], fallback=["primary", "secondary"])
    resp = await mgr.generate(LLMRequest(prompt="hi"), use_cache=False)
    assert resp.provider == "secondary"


@pytest.mark.asyncio
async def test_all_providers_fail_raises() -> None:
    bad1 = _BadProvider("a")
    bad2 = _BadProvider("b")
    mgr = _manager_with_providers([bad1, bad2])
    with pytest.raises(LLMError, match="all providers failed"):
        await mgr.generate(LLMRequest(prompt="hi"), use_cache=False)


@pytest.mark.asyncio
async def test_explicit_provider_selection() -> None:
    p1 = _GoodProvider("alpha")
    p2 = _GoodProvider("beta")
    mgr = _manager_with_providers([p1, p2])
    resp = await mgr.generate(LLMRequest(prompt="hi"), provider="beta", use_cache=False)
    assert resp.provider == "beta"
    assert p1.called == 0
    assert p2.called == 1


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_returns_cached_response() -> None:
    good = _GoodProvider()
    mgr = _manager_with_providers([good])
    req = LLMRequest(prompt="hello")
    resp1 = await mgr.generate(req, use_cache=True)
    resp2 = await mgr.generate(req, use_cache=True)
    assert resp2.cached is True
    assert good.called == 1  # only one actual call


@pytest.mark.asyncio
async def test_cache_key_differs_by_stop_sequence() -> None:
    """H5 regression: different stop sequences must not collide in cache."""
    good = _GoodProvider()
    mgr = _manager_with_providers([good])
    req_a = LLMRequest(prompt="hello", stop=["<END>"])
    req_b = LLMRequest(prompt="hello", stop=["</s>"])
    await mgr.generate(req_a, use_cache=True)
    resp_b = await mgr.generate(req_b, use_cache=True)
    assert resp_b.cached is False  # must NOT be a cache hit
    assert good.called == 2


@pytest.mark.asyncio
async def test_cache_key_differs_by_extra() -> None:
    """H5 regression: different extra params must produce different cache keys."""
    good = _GoodProvider()
    mgr = _manager_with_providers([good])
    req_a = LLMRequest(prompt="hello", extra={"top_k": 40})
    req_b = LLMRequest(prompt="hello", extra={"top_k": 100})
    await mgr.generate(req_a, use_cache=True)
    resp_b = await mgr.generate(req_b, use_cache=True)
    assert resp_b.cached is False
    assert good.called == 2


def test_lru_evicts_oldest() -> None:
    cache: _LRU = _LRU()
    dummy = LLMResponse(content="x", provider="p", model="m")
    for i in range(260):
        cache.put(f"k{i}", dummy)
    assert len(cache) == 256  # _CACHE_MAX
    assert "k0" not in cache
    assert "k259" in cache


# ---------------------------------------------------------------------------
# Dynamic Model Routing tests
# ---------------------------------------------------------------------------

from more_core.core.types import TaskType
from more_core.llm.dynamic_router import DynamicModelRouter


class _FakeLLMManagerForRouting:
    """Minimal LLMManager stub for DynamicModelRouter tests."""
    def __init__(self, providers=None):
        self._providers = dict(providers or {})

    def list_providers(self):
        return list(self._providers)

    async def health(self):
        return {name: True for name in self._providers}


def test_dynamic_router_resolves_alias():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    alias = router.resolve_alias("free-coder")
    assert alias is not None
    assert alias.provider == "openrouter"
    assert "qwen" in alias.model.lower()


def test_dynamic_router_get_binding_default():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    binding = router.get_binding(TaskType.CODE_GENERATION)
    assert binding.provider == "ollama"
    assert binding.model == "qwen2.5:7b"


def test_dynamic_router_select_provider():
    mgr = _FakeLLMManagerForRouting({"ollama": True})
    router = DynamicModelRouter(mgr)
    provider = router.select_provider(TaskType.NLP_TASK)
    assert provider == "ollama"


def test_dynamic_router_select_provider_unavailable():
    mgr = _FakeLLMManagerForRouting({"other": True})
    router = DynamicModelRouter(mgr)
    provider = router.select_provider(TaskType.NLP_TASK)
    assert provider is None


def test_dynamic_router_select_model():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    model = router.select_model(TaskType.NLP_TASK)
    assert model == "qwen2.5:7b"


def test_dynamic_router_update_task_binding():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    router.update_task_binding(TaskType.NLP_TASK, "custom", "custom-model")
    binding = router.get_binding(TaskType.NLP_TASK)
    assert binding.provider == "custom"
    assert binding.model == "custom-model"


def test_dynamic_router_fallback_chain():
    mgr = _FakeLLMManagerForRouting({"ollama": True, "lmstudio": True})
    router = DynamicModelRouter(mgr)
    chain = router.get_fallback_chain(TaskType.NLP_TASK)
    assert len(chain) >= 1
    providers = [p.provider for p in chain]
    assert "ollama" in providers


def test_dynamic_router_custom_fallback_chain():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    from more_core.llm.manager import ProviderModelPair
    binding = ProviderModelPair(provider="alpha", model="alpha-model")
    router.set_custom_fallback_chain("test_chain", [binding])
    router.set_binding(TaskType.CODE_GENERATION, binding)
    router._determine_chain_key = lambda tt: "test_chain"
    chain = router.get_fallback_chain(TaskType.CODE_GENERATION)
    assert chain[0].provider == "alpha"


def test_dynamic_router_remove_custom_chain():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    router.set_custom_fallback_chain("temp", [])
    assert "temp" in router._custom_fallback_chains
    router.remove_custom_fallback_chain("temp")
    assert "temp" not in router._custom_fallback_chains


def test_dynamic_router_get_routing_config():
    mgr = _FakeLLMManagerForRouting({"ollama": True})
    router = DynamicModelRouter(mgr)
    config = router.get_routing_config()
    assert "bindings" in config
    assert "fallback_chains" in config
    assert "aliases" in config
    assert "reasoning" in config
    assert "providers" in config
    assert "ollama" in config["providers"]
