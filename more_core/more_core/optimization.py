"""Performance Optimization Module - Caching, Connection Pooling, Retry Logic."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, TypeVar, Awaitable
from functools import wraps
from enum import Enum

logger = logging.getLogger(__name__)


class CacheStrategy(Enum):
    """Cache strategies."""
    NO_CACHE = "no_cache"
    LRU = "lru"
    TTL = "ttl"
    STALE_WHILE_REVALIDATE = "stale_while-revalidate"


@dataclass
class CacheConfig:
    """Cache configuration."""
    max_size: int = 1000
    ttl_seconds: int = 3600
    strategy: CacheStrategy = CacheStrategy.LRU


class RequestCache:
    """LRU Cache with TTL for LLM requests."""
    
    def __init__(self, config: CacheConfig | None = None):
        self._config = config or CacheConfig()
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
    
    def _key(self, prompt: str, model: str, **kwargs) -> str:
        raw = f"{model}:{prompt}:{sorted(kwargs.items())}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    
    async def get(self, prompt: str, model: str, **kwargs) -> Any | None:
        key = self._key(prompt, model, **kwargs)
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._hits += 1
                    self._cache.move_to_end(key)
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None
    
    async def set(self, prompt: str, model: str, value: Any, ttl: int | None = None) -> None:
        key = self._key(prompt, model)
        ttl = ttl or self._config.ttl_seconds
        
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self._config.max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = (value, time.time() + ttl)
    
    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
    
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0,
            "size": len(self._cache),
        }


T = TypeVar("T")


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retry_on: Callable[[Exception], bool] | None = None,
):
    """Decorator for retry logic with exponential backoff."""
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if retry_on and not retry_on(e):
                        raise
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (exponential_base ** attempt), max_delay)
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


def with_timeout(timeout_s: float, default: Any = None):
    """Decorator for timeout handling."""
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_s)
            except asyncio.TimeoutError:
                return default
        return wrapper
    return decorator


@dataclass
class CircuitState:
    """Circuit breaker state."""
    failures: int = 0
    last_failure_time: float = 0
    is_open: bool = False


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._state = CircuitState()
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        async with self._lock:
            if self._state.is_open:
                if time.time() - self._state.last_failure_time > self._recovery_timeout:
                    # Transition to half-open: allow probe calls
                    self._state.is_open = False
                    self._half_open_calls = 1
                else:
                    raise RuntimeError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._on_success()
            return result
        except Exception:
            async with self._lock:
                self._on_failure()
            raise
    
    def _on_success(self) -> None:
        self._state.failures = 0
        if self._half_open_calls > 0:
            self._half_open_calls += 1
            if self._half_open_calls >= self._half_open_max_calls:
                self._state.is_open = False
                self._half_open_calls = 0
    
    def _on_failure(self) -> None:
        self._state.failures += 1
        self._state.last_failure_time = time.time()
        if self._half_open_calls > 0:
            # Half-open probe failed — re-open circuit immediately
            self._state.is_open = True
            self._half_open_calls = 0
        elif self._state.failures >= self._failure_threshold:
            self._state.is_open = True
            self._half_open_calls = 0
    
    @property
    def state(self) -> str:
        if self._state.is_open:
            return "OPEN"
        elif self._half_open_calls > 0:
            return "HALF_OPEN"
        return "CLOSED"


class ConnectionPool:
    """Simple connection pool for HTTP clients."""
    
    def __init__(self, max_connections: int = 10, max_keepalive: int = 20):
        self._semaphore = asyncio.Semaphore(max_connections)
        self._max_keepalive = max_keepalive
        self._active = 0
        self._waiting = 0
    
    async def __aenter__(self):
        await self._semaphore.acquire()
        self._active += 1
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._active -= 1
        self._semaphore.release()
    
    @property
    def stats(self) -> dict:
        return {
            "active": self._active,
            "waiting": self._waiting,
            "max": self._semaphore._value + self._active,
        }


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float, burst: int = 1):
        self._rate = rate
        self._burst = burst
        self._tokens = burst
        self._last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    async def wait_for_token(self, tokens: int = 1) -> None:
        while not await self.acquire(tokens):
            await asyncio.sleep(0.1)