"""Channel Reconnect — auto-reconnect with exponential backoff.

Reference: OpenFang v0.6.7 reconnect logic.
Wraps channel adapters with automatic reconnection on failure,
exponential backoff, and jitter to prevent thundering herds.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import ChannelAdapter

_log = logging.getLogger(__name__)


@dataclass
class ReconnectConfig:
    """Configuration for reconnection behavior."""

    max_retries: int = 10  # 0 = infinite
    initial_delay_s: float = 1.0
    max_delay_s: float = 300.0  # 5 minutes cap
    backoff_factor: float = 2.0
    jitter: float = 0.3  # ±30% jitter
    reset_after_success_s: float = 60.0  # Reset backoff after stable connection


@dataclass
class ReconnectState:
    """Current reconnection state for a channel."""

    channel_name: str
    connected: bool = True
    attempt: int = 0
    last_disconnect: float | None = None
    last_reconnect: float | None = None
    total_disconnects: int = 0
    total_reconnects: int = 0
    current_delay_s: float = 1.0


class ReconnectManager:
    """Manages auto-reconnection for all channel adapters.

    Wraps adapters with exponential backoff reconnection logic.
    """

    def __init__(self, config: ReconnectConfig | None = None) -> None:
        self._config = config or ReconnectConfig()
        self._states: dict[str, ReconnectState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False

    def register(self, name: str, adapter: "ChannelAdapter") -> None:
        """Register an adapter for reconnection monitoring."""
        self._states[name] = ReconnectState(channel_name=name)

    def unregister(self, name: str) -> None:
        """Remove an adapter from monitoring."""
        task = self._tasks.pop(name, None)
        if task:
            task.cancel()
        self._states.pop(name, None)

    async def start(self) -> None:
        """Start monitoring all registered channels."""
        self._running = True
        _log.info("ReconnectManager started")

    async def stop(self) -> None:
        """Stop all reconnection tasks."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        _log.info("ReconnectManager stopped")

    async def on_disconnect(self, name: str, adapter: "ChannelAdapter") -> None:
        """Called when a channel disconnects. Starts reconnection loop."""
        state = self._states.get(name)
        if state is None:
            return

        state.connected = False
        state.last_disconnect = time.time()
        state.total_disconnects += 1
        _log.warning("Channel %s disconnected (total: %d)", name, state.total_disconnects)

        # Start reconnection task if not already running
        if name not in self._tasks or self._tasks[name].done():
            self._tasks[name] = asyncio.create_task(self._reconnect_loop(name, adapter))

    async def on_connect(self, name: str) -> None:
        """Called when a channel successfully connects."""
        state = self._states.get(name)
        if state is None:
            return

        state.connected = True
        state.attempt = 0
        state.current_delay_s = self._config.initial_delay_s
        state.last_reconnect = time.time()
        state.total_reconnects += 1
        _log.info("Channel %s reconnected (attempt %d)", name, state.total_reconnects)

    async def _reconnect_loop(self, name: str, adapter: "ChannelAdapter") -> None:
        """Reconnection loop with exponential backoff."""
        state = self._states[name]
        state.current_delay_s = self._config.initial_delay_s

        while self._running:
            if self._config.max_retries > 0 and state.attempt >= self._config.max_retries:
                _log.error("Channel %s: max retries (%d) exceeded", name, self._config.max_retries)
                break

            state.attempt += 1
            delay = self._calculate_delay(state)
            _log.info("Channel %s: reconnecting in %.1fs (attempt %d)", name, delay, state.attempt)

            await asyncio.sleep(delay)

            if not self._running:
                break

            try:
                await adapter.stop()
                await adapter.start()
                await self.on_connect(name)
                return  # Success
            except Exception as exc:
                _log.warning("Channel %s: reconnect failed: %s", name, exc)
                state.current_delay_s = min(
                    state.current_delay_s * self._config.backoff_factor,
                    self._config.max_delay_s,
                )

    def _calculate_delay(self, state: ReconnectState) -> float:
        """Calculate delay with jitter."""
        delay = state.current_delay_s
        jitter_range = delay * self._config.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return max(0.1, delay)

    def get_state(self, name: str) -> ReconnectState | None:
        return self._states.get(name)

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "connected": s.connected,
                "attempt": s.attempt,
                "total_disconnects": s.total_disconnects,
                "total_reconnects": s.total_reconnects,
                "last_disconnect": s.last_disconnect,
                "last_reconnect": s.last_reconnect,
            }
            for name, s in self._states.items()
        }

    def stats(self) -> dict[str, Any]:
        return {
            "monitored_channels": len(self._states),
            "disconnected": sum(1 for s in self._states.values() if not s.connected),
            "active_reconnects": sum(1 for t in self._tasks.values() if not t.done()),
            "config": {
                "max_retries": self._config.max_retries,
                "max_delay_s": self._config.max_delay_s,
                "backoff_factor": self._config.backoff_factor,
            },
        }
