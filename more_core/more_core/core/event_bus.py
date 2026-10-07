"""Asynchronous, single-process event bus with topic subscriptions.

Design goals:
- Decouple L0–L5 layers and support fan-out to observers (audit, metrics).
- Never block publishers; handlers run in tasks.
- Deterministic shutdown: ``stop()`` drains queued events.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

Handler = Callable[["Event"], Awaitable[None]]


@dataclass(slots=True)
class Event:
    topic: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str | None = None


class EventBus:
    def __init__(self, queue_size: int = 1024, max_pending: int = 1024) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._runner: asyncio.Task[None] | None = None
        self._running = False
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._max_pending = max_pending

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        self._subscribers[topic].append(handler)

        def _unsub() -> None:
            try:
                self._subscribers[topic].remove(handler)
            except ValueError:
                pass

        return _unsub

    async def publish(self, topic: str, data: Any = None, source: str | None = None) -> None:
        await self._queue.put(Event(topic=topic, data=data, source=source))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._runner = asyncio.create_task(self._run(), name="more-eventbus")

    async def stop(self) -> None:
        self._running = False
        if self._runner is not None:
            await self._queue.put(Event(topic="__shutdown__"))
            await self._runner
            self._runner = None
        # Drain all pending handler tasks to avoid data loss on shutdown.
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()

    async def _run(self) -> None:
        while self._running:
            event = await self._queue.get()
            if event.topic == "__shutdown__":
                break
            handlers = list(self._subscribers.get(event.topic, ()))
            # Also deliver to wildcard subscribers ("*").
            handlers.extend(self._subscribers.get("*", ()))
            if len(self._pending_tasks) >= self._max_pending:
                _log.warning(
                    "EventBus pending tasks exceeded %d, dropping handlers for topic=%s",
                    self._max_pending,
                    event.topic,
                )
                continue
            for handler in handlers:
                task = asyncio.create_task(self._safe_call(handler, event))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)

    @staticmethod
    async def _safe_call(handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:  # noqa: BLE001
            _log.warning("event handler for topic=%s failed", event.topic, exc_info=True)
