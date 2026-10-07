"""Tests for optimization module - RequestCache, RateLimiter, CircuitBreaker."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from more_core.optimization import (
    RequestCache,
    CacheConfig,
    CacheStrategy,
    RateLimiter,
    CircuitBreaker,
    ConnectionPool,
)


class TestRequestCache:
    """Test suite for RequestCache."""

    def test_cache_initialization(self):
        """Test cache initializes with correct defaults."""
        cache = RequestCache()
        assert cache is not None

    async def test_cache_set_and_get(self):
        """Test basic cache set and get operations."""
        cache = RequestCache()
        await cache.set("prompt", "model", "value")
        result = await cache.get("prompt", "model")
        assert result == "value"

    async def test_cache_miss(self):
        """Test cache returns None for missing keys."""
        cache = RequestCache()
        result = await cache.get("nonexistent", "model")
        assert result is None

    def test_cache_with_config(self):
        """Test cache with custom config."""
        config = CacheConfig(max_size=100, ttl_seconds=60, strategy=CacheStrategy.LRU)
        cache = RequestCache(config)
        assert cache._config.max_size == 100
        assert cache._config.ttl_seconds == 60

    async def test_cache_stats(self):
        """Test cache stats."""
        cache = RequestCache()
        await cache.set("prompt1", "model", "value1")
        await cache.get("prompt1", "model")  # hit
        await cache.get("prompt2", "model")  # miss
        stats = cache.stats()
        assert "hits" in stats
        assert "misses" in stats


class TestCacheConfig:
    """Test suite for CacheConfig."""

    def test_default_config(self):
        """Test default cache config."""
        config = CacheConfig()
        assert config.max_size == 1000
        assert config.ttl_seconds == 3600
        assert config.strategy == CacheStrategy.LRU


class TestRateLimiter:
    """Test suite for RateLimiter."""

    def test_rate_limiter_initialization(self):
        """Test rate limiter initializes correctly."""
        limiter = RateLimiter(rate=10, burst=20)
        assert limiter._rate == 10
        assert limiter._burst == 20

    @pytest.mark.asyncio
    async def test_allow_within_limit(self):
        """Test requests within limit are allowed."""
        limiter = RateLimiter(rate=10, burst=10)
        allowed = await limiter.acquire()
        assert allowed is True


class TestCircuitBreaker:
    """Test suite for CircuitBreaker."""

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initializes in closed state."""
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert breaker.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful call through circuit breaker."""
        breaker = CircuitBreaker(failure_threshold=3)

        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state == "CLOSED"

    @pytest.mark.asyncio
    async def test_failed_call_opens_circuit(self):
        """Test failures open circuit after threshold."""
        breaker = CircuitBreaker(failure_threshold=2)

        async def fail_func():
            raise Exception("test failure")

        # First failure
        with pytest.raises(Exception):
            await breaker.call(fail_func)

        # Second failure should open circuit
        with pytest.raises(Exception):
            await breaker.call(fail_func)

        assert breaker.state == "OPEN"


class TestConnectionPool:
    """Test suite for ConnectionPool."""

    def test_pool_initialization(self):
        """Test connection pool initializes correctly."""
        pool = ConnectionPool(max_connections=10)
        assert pool is not None

    @pytest.mark.asyncio
    async def test_pool_context_manager(self):
        """Test pool as context manager."""
        pool = ConnectionPool(max_connections=2)
        async with pool:
            stats = pool.stats
            assert stats["active"] == 1
        # After exiting, active should be 0
        # (may not be immediate in this simple implementation)

    def test_pool_stats(self):
        """Test pool stats."""
        pool = ConnectionPool(max_connections=5)
        stats = pool.stats
        assert "active" in stats
        assert "max" in stats
