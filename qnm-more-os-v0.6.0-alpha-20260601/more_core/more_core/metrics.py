"""Performance monitoring and metrics collection."""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from collections import defaultdict
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Single metric data point."""
    name: str
    value: float
    timestamp: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass 
class PerformanceSnapshot:
    """Snapshot of system performance."""
    timestamp: float
    layer_durations: dict[str, float]
    total_requests: int
    success_count: int
    failure_count: int
    avg_duration_ms: float
    p95_duration_ms: float
    cache_hit_rate: float
    memory_usage_mb: float


class MetricsCollector:
    """Collects and aggregates performance metrics."""

    def __init__(self, window_size: int = 1000):
        self._window_size = window_size
        self._lock = threading.Lock()
        self._request_durations: list[float] = []
        self._layer_durations: dict[str, list[float]] = defaultdict(list)
        self._request_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._start_time = time.time()

    def record_request(self, duration_ms: float, success: bool) -> None:
        """Record a request completion.
        
        Args:
            duration_ms: Request duration in milliseconds
            success: Whether request succeeded
        """
        with self._lock:
            self._request_durations.append(duration_ms)
            if len(self._request_durations) > self._window_size:
                self._request_durations.pop(0)
            self._request_count += 1
            if success:
                self._success_count += 1
            else:
                self._failure_count += 1

    def record_layer(self, layer: str, duration_ms: float) -> None:
        """Record layer execution duration.
        
        Args:
            layer: Layer identifier (L0, L1, etc.)
            duration_ms: Execution duration in milliseconds
        """
        with self._lock:
            self._layer_durations[layer].append(duration_ms)
            if len(self._layer_durations[layer]) > self._window_size:
                self._layer_durations[layer].pop(0)

    def get_percentile(self, values: list[float], percentile: float) -> float:
        """Calculate percentile value from a list.
        
        Args:
            values: List of numeric values
            percentile: Percentile to calculate (0-100)
            
        Returns:
            Value at the specified percentile
        """
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * percentile / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    def snapshot(self, cache_hit_rate: float = 0.0, memory_mb: float = 0.0) -> PerformanceSnapshot:
        with self._lock:
            durations = self._request_durations
            avg_duration = sum(durations) / len(durations) if durations else 0
            p95 = self.get_percentile(durations, 95)
            
            layer_stats = {}
            for layer, vals in self._layer_durations.items():
                layer_stats[layer] = sum(vals) / len(vals) if vals else 0

            return PerformanceSnapshot(
                timestamp=time.time(),
                layer_durations=layer_stats,
                total_requests=self._request_count,
                success_count=self._success_count,
                failure_count=self._failure_count,
                avg_duration_ms=avg_duration,
                p95_duration_ms=p95,
                cache_hit_rate=cache_hit_rate,
                memory_usage_mb=memory_mb,
            )

    def reset(self) -> None:
        with self._lock:
            self._request_durations.clear()
            self._layer_durations.clear()
            self._request_count = 0
            self._success_count = 0
            self._failure_count = 0
            self._start_time = time.time()


class Timer:
    """Context manager for timing operations."""

    def __init__(self, collector: MetricsCollector, label: str):
        self._collector = collector
        self._label = label
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self._start) * 1000
        self._collector.record_layer(self._label, duration_ms)


_global_collector = MetricsCollector()


def get_collector() -> MetricsCollector:
    return _global_collector


@contextmanager
def timer(label: str):
    """Global timer context manager."""
    with Timer(_global_collector, label) as t:
        yield t