"""Tests for LLMManager multi-provider fallback and caching."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from more_core.core.errors import LLMError
from more_core.core.types import TaskType
from more_core.llm.dynamic_router import DynamicModelRouter
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
    await mgr.generate(req, use_cache=True)
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


def test_dynamic_router_get_binding_default(monkeypatch):
    # Isolate from env overrides (MORE_TASK_MODEL_*) so the static default is tested.
    monkeypatch.delenv("MORE_TASK_MODEL_CODE_GENERATION", raising=False)
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    binding = router.get_binding(TaskType.CODE_GENERATION)
    assert binding.provider == "lmstudio"
    assert binding.model == "ornith-1.5-35b-a3b"  # Ornith-1.5 coder 变体


def test_dynamic_router_env_override(monkeypatch):
    monkeypatch.setenv("MORE_TASK_MODEL_CODE_GENERATION", "ollama:qwen2.5:7b")
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    binding = router.get_binding(TaskType.CODE_GENERATION)
    assert binding.provider == "ollama"
    assert binding.model == "qwen2.5:7b"


def test_code_primary_chain_is_lmstudio_first(monkeypatch):
    monkeypatch.delenv("MORE_TASK_MODEL_CODE_GENERATION", raising=False)
    mgr = _FakeLLMManagerForRouting({"ollama": True, "lmstudio": True})
    router = DynamicModelRouter(mgr)
    chain = router.get_fallback_chain(TaskType.CODE_GENERATION)
    assert chain[0].provider == "lmstudio"
    assert chain[0].model == "ornith-1.5-35b-a3b"


def test_dynamic_router_select_provider():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True})
    router = DynamicModelRouter(mgr)
    provider = router.select_provider(TaskType.NLP_TASK)
    assert provider == "lmstudio"


def test_dynamic_router_select_provider_unavailable():
    mgr = _FakeLLMManagerForRouting({"other": True})
    router = DynamicModelRouter(mgr)
    provider = router.select_provider(TaskType.NLP_TASK)
    assert provider is None


def test_dynamic_router_select_model():
    mgr = _FakeLLMManagerForRouting()
    router = DynamicModelRouter(mgr)
    model = router.select_model(TaskType.NLP_TASK)
    assert model == "ornith-ai/ornith-1.5-9b"


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


# ---------------------------------------------------------------------------
# 逐级降智 (tiered capability degradation) — difficulty-aware routing
# ---------------------------------------------------------------------------

def test_tier_index_maps_difficulty():
    from more_core.llm.task_router import tier_index_for_difficulty
    assert tier_index_for_difficulty(None) == 1      # 默认主力
    assert tier_index_for_difficulty(1) == 2         # 琐碎 → 9b
    assert tier_index_for_difficulty(3) == 2         # 简单 → 9b
    assert tier_index_for_difficulty(5) == 1         # 中等 → 35b
    assert tier_index_for_difficulty(7) == 1         # 中等 → 35b
    assert tier_index_for_difficulty(9) == 0         # 复杂 → 35b reasoning


def test_tier_ladder_has_four_distinct_models():
    from more_core.llm.task_router import MODEL_TIER_LADDER, TIER_PROVIDERS
    assert len(MODEL_TIER_LADDER) == 4
    assert len(set(MODEL_TIER_LADDER)) == 4  # 每级真实模型互不相同 (T0 != T1)
    assert len(TIER_PROVIDERS) == 4


def test_tier_params_balance_thinking_and_budget():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    # 高难度 → 开 thinking + 大预算
    hard = router.tier_params(9)
    assert hard["enable_thinking"] is True
    assert hard["max_tokens"] >= 4096
    # 简单任务 → 关 thinking + 小预算 (避开推理 token 开销)
    easy = router.tier_params(2)
    assert easy["enable_thinking"] is False
    assert easy["max_tokens"] <= 2048


def test_apply_tier_params_only_raises_budget():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    # difficulty=None → 不干预
    req = LLMRequest(prompt="hi")
    assert router.apply_tier_params(req, None) is req
    assert req.max_tokens == 1024  # default 不会被 None difficulty 覆写
    # 高难度 → 提升 max_tokens 下限, 打开 thinking
    req2 = LLMRequest(prompt="hi", max_tokens=100)
    router.apply_tier_params(req2, 9)
    assert req2.enable_thinking is True
    assert req2.max_tokens >= 4096
    # 调用方预算更大时不被压低
    req3 = LLMRequest(prompt="hi", max_tokens=20000)
    router.apply_tier_params(req3, 9)
    assert req3.max_tokens == 20000


def test_select_model_uses_light_tier_for_easy():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    assert router.select_model(TaskType.NLP_TASK, difficulty=2) == "ornith-ai/ornith-1.5-9b"


def test_select_model_uses_strong_tier_for_hard():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    # 高难度 reasoning 任务 (R1-B T0 whitelist) 走 T0 推理蒸馏
    assert (
        router.select_model(TaskType.MATH_REASONING, difficulty=9)
        == "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
    )
    # 非 reasoning 白名单任务 (CODE_GENERATION) 即使 diff=9 也 cap 到 T1 (R1-B 限流加固)
    assert (
        router.select_model(TaskType.CODE_GENERATION, difficulty=9)
        == "ornith-1.5-35b-a3b"
    )


def test_fallback_chain_degrades_tier_by_tier():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    # 简单任务 → 从 9b 开始逐级降智
    chain = router.get_fallback_chain(TaskType.NLP_TASK, difficulty=2)
    assert chain[0].model == "ornith-ai/ornith-1.5-9b"
    assert chain[-1].provider == "ollama"  # 最终兜底
    # 复杂 reasoning 任务 (R1-B T0 whitelist) → 从 T0 35b 推理蒸馏开始
    chain_hard = router.get_fallback_chain(TaskType.MATH_REASONING, difficulty=9)
    assert chain_hard[0].model == "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled"
    assert chain_hard[0].provider == "lmstudio"
    # 非 reasoning 白名单 CODE_GENERATION 即使 9 分也 cap 到 T1 35b 主力 (R1-B)
    chain_code_hard = router.get_fallback_chain(TaskType.CODE_GENERATION, difficulty=9)
    assert chain_code_hard[0].model == "ornith-1.5-35b-a3b"
    assert chain_code_hard[0].provider == "lmstudio"


def test_fallback_chain_dedupes_consecutive_duplicates():
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    chain = router.get_fallback_chain(TaskType.CODE_GENERATION, difficulty=9)
    models = [(p.provider, p.model) for p in chain]
    assert len(models) == len(set(models))  # 无连续重复


def test_reasoning_alias_not_used_when_provider_unavailable():
    # 只配置本地 provider，reasoning 别名指向 openai/o4-mini → 不应被选中
    mgr = _FakeLLMManagerForRouting({"lmstudio": True, "ollama": True})
    router = DynamicModelRouter(mgr)
    binding = router.get_binding(TaskType.MATH_REASONING, difficulty=9)
    assert binding.provider in {"lmstudio", "ollama"}


# ---------------------------------------------------------------------------
# Health-check bounding / failure-count TTL / parallel-task hygiene
# ---------------------------------------------------------------------------

class _HangingHealthProvider:
    def __init__(self, name: str = "hanging") -> None:
        self.name = name
        self.model = "hang-model"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="ok", provider=self.name, model=self.model)

    async def health(self) -> bool:
        await asyncio.sleep(100)  # simulates an endpoint that hangs
        return True


@pytest.mark.asyncio
async def test_health_check_is_time_bounded() -> None:
    import time as _time

    mgr = _manager_with_providers([_HangingHealthProvider()])
    t0 = _time.monotonic()
    healthy = await mgr._check_health_cached("hanging")
    elapsed = _time.monotonic() - t0
    assert healthy is False
    assert elapsed < 10  # bounded well below the 100s hang


@pytest.mark.asyncio
async def test_failure_count_skips_then_decays_after_ttl() -> None:

    mgr = _manager_with_providers([_GoodProvider("flaky")])
    for _ in range(3):
        mgr._record_failure("flaky", None)
    assert mgr._should_skip("flaky", None)

    future = time.monotonic() + 120
    with patch("more_core.llm.manager.time.monotonic", return_value=future):
        assert mgr._should_skip("flaky", None) is False


@pytest.mark.asyncio
async def test_failure_count_cleared_on_success() -> None:
    class _RecoveringProvider:
        def __init__(self) -> None:
            self.name = "recover"
            self.model = "m"
            self.fail_times = 1

        async def generate(self, request: LLMRequest) -> LLMResponse:
            if self.fail_times > 0:
                self.fail_times -= 1
                raise LLMError("transient")
            return LLMResponse(content="ok", provider=self.name, model=self.model)

        async def health(self) -> bool:
            return True

    mgr = _manager_with_providers([_RecoveringProvider()])
    with pytest.raises(LLMError):
        await mgr.generate(LLMRequest(prompt="hi"), use_cache=False)
    assert mgr.get_failure_counts()["recover:default"] == 1

    resp = await mgr.generate(LLMRequest(prompt="hi"), use_cache=False)
    assert resp.content == "ok"
    assert "recover:default" not in mgr.get_failure_counts()


class _CancellationBombProvider:
    """Raises a non-cancellation error while being cancelled."""

    def __init__(self, name: str = "bomb") -> None:
        self.name = name
        self.model = "bomb-model"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            await asyncio.sleep(10)
        finally:
            raise LLMError("cleanup failed during cancellation")

    async def health(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_generate_parallel_retrieves_cancelled_task_exceptions() -> None:
    from more_core.llm.manager import ProviderModelPair

    captured: list[dict[str, object]] = []
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: captured.append(ctx))
    try:
        fast = _GoodProvider("fast")
        bomb = _CancellationBombProvider("bomb")
        mgr = _manager_with_providers([fast, bomb])
        resp = await mgr.generate_parallel(
            LLMRequest(prompt="hi"),
            candidates=[
                ProviderModelPair("fast", "fast-model"),
                ProviderModelPair("bomb", "bomb-model"),
            ],
            use_cache=False,
            timeout_s=5,
        )
        assert resp.provider == "fast"
        for _ in range(20):
            await asyncio.sleep(0)
            if captured:
                break
        messages = [str(c.get("message")) for c in captured]
        assert not any("Task exception was never retrieved" in m for m in messages), messages
    finally:
        loop.set_exception_handler(old_handler)


# ---------------------------------------------------------------------------
# 生产事故回归：超时失败必须"可诊断 + 有耗时"（此前记成 error='' / latency=0）
# ---------------------------------------------------------------------------


def test_exc_summary_names_timeout_and_blank_errors():
    from more_core.llm.manager import _exc_summary

    # asyncio.TimeoutError 的 str() 是空串 → 必须显式命名并带耗时
    msg = _exc_summary(asyncio.TimeoutError(), 1234.0)
    assert "timeout" in msg.lower()
    assert "1234" in msg
    # 其他异常消息为空 → 回退到类型名；非空 → 原样
    assert _exc_summary(RuntimeError(""), 0.0) == "RuntimeError"
    assert _exc_summary(RuntimeError("boom"), 0.0) == "boom"


def test_fallback_deadline_respects_env_override(monkeypatch):
    from more_core.llm import manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "_FALLBACK_DEADLINE_S", 240.0)
    assert mgr_mod._effective_fallback_deadline(None) == 240.0
    # 合约超时再大也被上限钳制
    assert mgr_mod._effective_fallback_deadline(10_000.0) == 240.0


@pytest.mark.asyncio
async def test_timeout_failure_records_diagnosable_error(monkeypatch):
    from more_core.governance import observability as obs
    from more_core.llm import manager as mgr_mod

    class _SlowProvider:
        name = "slow"
        model = "slow-model"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            await asyncio.sleep(5)
            return LLMResponse(content="late", provider="slow", model="slow-model")

        async def health(self) -> bool:
            return True

    # 把链级预算压到 0.2s，让 slow provider 必然超时（测试可控且快）
    monkeypatch.setattr(mgr_mod, "_FALLBACK_DEADLINE_S", 0.2)
    monkeypatch.setattr(mgr_mod, "_FALLBACK_CONTRACT_HEADROOM_S", 0.0)

    mgr = _manager_with_providers([_SlowProvider()])
    with pytest.raises(LLMError):
        await mgr.generate(LLMRequest(prompt="hi", max_tokens=8))

    rows = obs.query_recent_llm(limit=5)
    assert rows, "超时失败也必须留痕（不能被静默丢弃）"
    row = rows[0]
    assert row["success"] == 0
    err = (row["error"] or "").lower()
    assert "timeout" in err, f"超时必须给出可诊断原因，实际 error={row['error']!r}"
    assert row["latency_ms"] > 0, "失败也应记录真实耗时（此前恒为 0）"


@pytest.mark.asyncio
async def test_slow_primary_does_not_starve_fallback(monkeypatch):
    """回归：慢的首选 provider 不得吃光整条链预算，否则兜底永远轮不到。

    事故形态：链 = 35B(极慢) → 9B(可用)，90s 预算被 35B 全部消耗，
    `remaining<=0` 直接抛错，9B 根本没机会执行 → 成功率 0%。
    """
    from more_core.llm import manager as mgr_mod

    class _SlowProvider:
        name = "slow"
        model = "slow-model"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            await asyncio.sleep(30)  # 远超预算
            return LLMResponse(content="slow", provider="slow", model="slow-model")

        async def health(self) -> bool:
            return True

    class _FastProvider:
        name = "fast"
        model = "fast-model"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(content="fast!", provider="fast", model="fast-model")

        async def health(self) -> bool:
            return True

    # 2.0s 预算 → 慢 provider 分到 1.0s 切片，兜底仍有 ~1.0s（留足时序余量）
    monkeypatch.setattr(mgr_mod, "_FALLBACK_DEADLINE_S", 2.0)
    monkeypatch.setattr(mgr_mod, "_FALLBACK_CONTRACT_HEADROOM_S", 0.0)
    mgr = _manager_with_providers(
        [_SlowProvider(), _FastProvider()], fallback=["slow", "fast"]
    )

    resp = await mgr.generate(LLMRequest(prompt="hi", max_tokens=8))
    assert resp.content == "fast!", "慢首选超时后，兜底 provider 必须被真正尝试"


# ---------------------------------------------------------------------------
# 回归：state.provider 不得把兜底链塌缩成单 provider（历史"成功率 0%"根因）
# ---------------------------------------------------------------------------


class _HealthyButFailing:
    """健康检查通过，但 generate 必然失败（用于观察链是否真的往下走）。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.called = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.called += 1
        raise LLMError(f"{self.name} down")

    async def health(self) -> bool:
        return True


def _state(provider: str, model: str):
    from more_core.llm.state_manager import LLMStateManager

    sm = LLMStateManager()
    sm.update_state(provider=provider, model=model)
    return sm


@pytest.mark.asyncio
async def test_fallback_chain_not_collapsed_by_state_provider():
    p1, p2 = _HealthyButFailing("lmstudio"), _HealthyButFailing("ollama")
    mgr = _manager_with_providers([p1, p2], fallback=["lmstudio", "ollama"])
    mgr._state_manager = _state("lmstudio", "ornith-1.5-35b-a3b")

    with pytest.raises(LLMError):
        await mgr.generate(LLMRequest(prompt="hi", max_tokens=4))

    assert p1.called == 1
    assert p2.called == 1, "state.provider 不得把兜底链塌缩成单 provider"


@pytest.mark.asyncio
async def test_fallback_resolves_model_per_provider():
    """state.model 只适用于 state.provider；其它 provider 用自己的默认模型。"""
    seen: dict[str, list] = {"lmstudio": [], "ollama": []}

    class _Rec:
        def __init__(self, name: str) -> None:
            self.name = name
            self.model = f"{name}-default"

        async def generate(self, request: LLMRequest) -> LLMResponse:
            seen[self.name].append(request.model_override)
            if self.name == "lmstudio":
                raise LLMError("lmstudio down")
            return LLMResponse(content="ok", provider=self.name, model=self.model)

        async def health(self) -> bool:
            return True

    mgr = _manager_with_providers([_Rec("lmstudio"), _Rec("ollama")],
                                  fallback=["lmstudio", "ollama"])
    mgr._state_manager = _state("lmstudio", "ornith-1.5-35b-a3b")

    resp = await mgr.generate(LLMRequest(prompt="hi", max_tokens=4))
    assert resp.content == "ok"
    assert seen["lmstudio"] == ["ornith-1.5-35b-a3b"]  # 匹配 state.provider → 用 state.model
    assert seen["ollama"] == [None]                    # 其它 provider 用自己的默认模型


@pytest.mark.asyncio
async def test_explicit_provider_still_pins_single_provider():
    p1, p2 = _HealthyButFailing("lmstudio"), _HealthyButFailing("ollama")
    mgr = _manager_with_providers([p1, p2], fallback=["lmstudio", "ollama"])
    mgr._state_manager = _state("lmstudio", "m")

    with pytest.raises(LLMError):
        await mgr.generate(LLMRequest(prompt="hi", max_tokens=4), provider="ollama")

    assert p1.called == 0, "显式 pin provider 时不应再走其它 provider"
    assert p2.called == 1


@pytest.mark.asyncio
async def test_state_provider_preference_orders_chain_without_dropping():
    order: list[str] = []

    class _Rec:
        def __init__(self, name: str) -> None:
            self.name = name
            self.model = name

        async def generate(self, request: LLMRequest) -> LLMResponse:
            order.append(self.name)
            raise LLMError(f"{self.name} down")

        async def health(self) -> bool:
            return True

    mgr = _manager_with_providers([_Rec("lmstudio"), _Rec("ollama")],
                                  fallback=["lmstudio", "ollama"])
    mgr._state_manager = _state("ollama", "qwen2.5:7b")

    with pytest.raises(LLMError):
        await mgr.generate(LLMRequest(prompt="hi", max_tokens=4))

    assert order[0] == "ollama", "state.provider 应作为偏好排在链首"
    assert set(order) == {"lmstudio", "ollama"}, "偏好排序不得删除兜底 provider"
