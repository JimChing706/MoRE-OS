"""Tests for kernel performance infrastructure: rate limiter, circuit breaker, L0 subtask integration."""

import asyncio

import pytest

from more_core.core.types import TaskRequest, TaskStatus, TaskType
from more_core.optimization import RateLimiter, CircuitBreaker, RequestCache, CacheConfig


# --- Rate Limiter Tests ---


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_burst():
    rl = RateLimiter(rate=10.0, burst=5)
    results = [await rl.acquire() for _ in range(5)]
    assert all(results), "All requests within burst should be allowed"


@pytest.mark.asyncio
async def test_rate_limiter_rejects_over_burst():
    rl = RateLimiter(rate=1.0, burst=2)
    await rl.acquire()
    await rl.acquire()
    assert not await rl.acquire(), "Third request should be rejected"


@pytest.mark.asyncio
async def test_rate_limiter_replenishes_tokens():
    rl = RateLimiter(rate=100.0, burst=1)
    await rl.acquire()
    assert not await rl.acquire()
    await asyncio.sleep(0.02)  # 100 tokens/s → ~2 tokens in 20ms
    assert await rl.acquire()


# --- Circuit Breaker Tests ---


@pytest.mark.asyncio
async def test_circuit_breaker_closed_on_success():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

    async def ok():
        return "success"

    result = await cb.call(ok)
    assert result == "success"
    assert cb.state == "CLOSED"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)

    async def fail():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(fail)

    assert cb.state == "OPEN"

    with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
        await cb.call(fail)


@pytest.mark.asyncio
async def test_circuit_breaker_recovers():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)

    async def fail():
        raise RuntimeError("boom")

    async def ok():
        return "recovered"

    with pytest.raises(RuntimeError):
        await cb.call(fail)
    assert cb.state == "OPEN"

    await asyncio.sleep(0.06)
    result = await cb.call(ok)
    assert result == "recovered"


# --- Request Cache Tests ---


def test_cache_stores_and_retrieves():
    cache = RequestCache(CacheConfig(max_size=10, ttl_seconds=60))
    cache.set("hello", "model-a", {"answer": 42})
    assert cache.get("hello", "model-a") == {"answer": 42}


def test_cache_respects_ttl():
    import time

    cache = RequestCache(CacheConfig(max_size=10, ttl_seconds=0))
    cache.set("hello", "model-a", "result", ttl=0)
    time.sleep(0.01)
    assert cache.get("hello", "model-a") is None


def test_cache_evicts_lru():
    cache = RequestCache(CacheConfig(max_size=2, ttl_seconds=60))
    cache.set("a", "m", 1)
    cache.set("b", "m", 2)
    cache.set("c", "m", 3)  # should evict 'a'
    assert cache.get("a", "m") is None
    assert cache.get("b", "m") == 2
    assert cache.get("c", "m") == 3


def test_cache_stats():
    cache = RequestCache(CacheConfig(max_size=10, ttl_seconds=60))
    cache.set("x", "m", "val")
    cache.get("x", "m")  # hit
    cache.get("y", "m")  # miss
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


# --- Rate Limiter Integration with Execute ---


@pytest.mark.asyncio
async def test_execute_respects_rate_limit(core):
    # Drain all tokens from the rate limiter
    core._rate_limiter = RateLimiter(rate=0.1, burst=1)
    await core._rate_limiter.acquire()  # consume the one token

    req = TaskRequest(type=TaskType.NLP_TASK, query="test")
    result = await core.execute(req)
    assert result.status == TaskStatus.REJECTED
    assert "rate limit" in result.output


# --- L0 Subtask Integration ---


@pytest.mark.asyncio
async def test_l0_uses_decomposed_subtasks(core):
    """When L4 decomposes, L0 should include subtasks in the prompt."""
    await core.event_bus.start()
    try:
        req = TaskRequest(type=TaskType.NLP_TASK, query="hello")
        from more_core.layers.base import LayerContext
        ctx = LayerContext(core=core, request=req)
        # Simulate L4 decomposition
        ctx.scratch["plan"] = {
            "subtasks": ["step one", "step two", "step three"],
            "decomposed": True,
            "difficulty": 8,
        }

        from more_core.layers.l0_execution import ExecutionLayer
        layer = ExecutionLayer()
        result = await layer.process(ctx)
        # Output should be "fake-reply" from the mock LLM
        assert result.output == "fake-reply"
    finally:
        await core.event_bus.stop()


# --- Circuit Breaker + LLM Integration ---


@pytest.mark.asyncio
async def test_llm_generate_safe_uses_circuit_breaker(core):
    """The llm_generate_safe helper should wrap LLM calls with the circuit breaker."""
    from more_core.llm.provider import LLMRequest

    req = LLMRequest(prompt="hello", system="sys")
    resp = await core.llm_generate_safe(req)
    assert resp.content == "fake-reply"
    assert core._llm_circuit_breaker.state == "CLOSED"


# --- Task-Level Result Caching ---


@pytest.mark.asyncio
async def test_task_result_caching(core):
    """Second identical query should hit cache and return immediately."""
    req1 = TaskRequest(type=TaskType.NLP_TASK, query="cached hello")
    result1 = await core.execute(req1)
    assert result1.status == TaskStatus.SUCCESS

    req2 = TaskRequest(type=TaskType.NLP_TASK, query="cached hello")
    result2 = await core.execute(req2)
    assert result2.status == TaskStatus.SUCCESS
    assert result2.output == result1.output
    assert result2.performance.total_duration_ms == 0.0  # served from cache


# --- L4 Complexity Estimation ---


def test_complexity_bonus_english():
    from more_core.layers.l4_cognition import _estimate_complexity_bonus

    assert _estimate_complexity_bonus("simple hello") == 0
    assert _estimate_complexity_bonus("integrate distributed services") >= 2
    assert _estimate_complexity_bonus("optimize architecture") >= 2


def test_complexity_bonus_chinese():
    from more_core.layers.l4_cognition import _estimate_complexity_bonus

    assert _estimate_complexity_bonus("简单的问候") == 0
    assert _estimate_complexity_bonus("分布式架构优化") >= 2


def test_complexity_bonus_capped():
    from more_core.layers.l4_cognition import _estimate_complexity_bonus

    heavy = "integrate distributed concurrent optimize architecture security refactor"
    assert _estimate_complexity_bonus(heavy) == 3  # capped at 3


# --- Correlation Context ---


def test_request_context_lifecycle():
    from more_core.core.request_context import RequestContext, set_context, get_context, clear_context

    assert get_context() is None
    ctx = RequestContext(task_id="t-123", actor="test_user")
    token = set_context(ctx)
    assert get_context() is not None
    assert get_context().task_id == "t-123"
    clear_context(token)
    assert get_context() is None
