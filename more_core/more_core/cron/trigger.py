"""Trigger engine for event-based task execution."""

from __future__ import annotations

import asyncio
import logging
import re
from asyncio import Task as AsyncTask
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class TriggerEventType(Enum):
    """Types of trigger events."""

    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    USER_JOINED = "user.joined"
    USER_LEFT = "user.left"
    FILE_UPLOADED = "file.uploaded"
    API_CALLED = "api.called"
    CUSTOM = "custom"


@dataclass
class TriggerEvent:
    """Represents a trigger event."""

    event_type: TriggerEventType
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    correlation_id: str | None = None


@dataclass
class EventPattern:
    """Pattern for matching events."""

    event_type: TriggerEventType | None = None
    source_pattern: str | None = None
    data_pattern: dict[str, Any] | None = None
    custom_filter: Callable[[TriggerEvent], bool] | None = None

    def matches(self, event: TriggerEvent) -> bool:
        """Check if event matches pattern."""
        if self.event_type and event.event_type != self.event_type:
            return False

        if self.source_pattern and not re.match(self.source_pattern, event.source):
            return False

        if self.data_pattern:
            for key, value in self.data_pattern.items():
                if key not in event.data or event.data[key] != value:
                    return False

        if self.custom_filter:
            return self.custom_filter(event)

        return True


@dataclass
class Trigger:
    """Trigger definition."""

    trigger_id: str
    name: str
    pattern: EventPattern
    handler: Callable[[TriggerEvent], Awaitable[Any]]
    enabled: bool = True
    description: str = ""
    cooldown_s: float = 0.0
    max_executions: int = 0
    execution_count: int = 0
    last_execution: float | None = None
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


class TriggerEngine:
    """Event-driven trigger engine."""

    def __init__(self) -> None:
        self._triggers: dict[str, Trigger] = {}
        self._running = False
        self._event_queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        self._processor_task: AsyncTask[Any] | None = None
        self._event_history: list[TriggerEvent] = []
        self._max_history = 1000

    def add_trigger(
        self,
        trigger_id: str,
        name: str,
        pattern: EventPattern,
        handler: Callable[[TriggerEvent], Awaitable[Any]],
        enabled: bool = True,
        description: str = "",
        cooldown_s: float = 0.0,
        max_executions: int = 0,
    ) -> Trigger:
        """Add a trigger."""
        trigger = Trigger(
            trigger_id=trigger_id,
            name=name,
            pattern=pattern,
            handler=handler,
            enabled=enabled,
            description=description,
            cooldown_s=cooldown_s,
            max_executions=max_executions,
        )

        self._triggers[trigger_id] = trigger
        _log.info(f"Added trigger: {trigger_id}")
        return trigger

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger."""
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            _log.info(f"Removed trigger: {trigger_id}")
            return True
        return False

    def get_trigger(self, trigger_id: str) -> Trigger | None:
        """Get a trigger."""
        return self._triggers.get(trigger_id)

    def list_triggers(self) -> list[Trigger]:
        """List all triggers."""
        return list(self._triggers.values())

    def enable_trigger(self, trigger_id: str) -> bool:
        """Enable a trigger."""
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.enabled = True
            return True
        return False

    def disable_trigger(self, trigger_id: str) -> bool:
        """Disable a trigger."""
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.enabled = False
            return True
        return False

    async def start(self) -> None:
        """Start the trigger engine."""
        self._running = True
        self._processor_task = asyncio.create_task(self._process_events())
        _log.info("Trigger engine started")

    async def stop(self) -> None:
        """Stop the trigger engine."""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        _log.info("Trigger engine stopped")

    async def emit(self, event: TriggerEvent) -> None:
        """Emit an event to the trigger engine."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        await self._event_queue.put(event)

    async def emit_simple(
        self,
        event_type: TriggerEventType,
        source: str,
        data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit a simple event."""
        event = TriggerEvent(
            event_type=event_type,
            source=source,
            data=data or {},
            correlation_id=correlation_id,
        )
        await self.emit(event)

    async def _process_events(self) -> None:
        """Process events from the queue."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,
                )

                await self._handle_event(event)

            except asyncio.TimeoutError:
                continue
            except Exception as e:  # noqa: BLE001
                _log.error(f"Error processing event: {e}")

    async def _handle_event(self, event: TriggerEvent) -> None:
        """Handle a single event."""
        for trigger in self._triggers.values():
            if not trigger.enabled:
                continue

            if not trigger.pattern.matches(event):
                continue

            if trigger.cooldown_s and trigger.last_execution:
                elapsed = event.timestamp - trigger.last_execution
                if elapsed < trigger.cooldown_s:
                    _log.debug(f"Trigger {trigger.name} in cooldown")
                    continue

            if trigger.max_executions and trigger.execution_count >= trigger.max_executions:
                _log.info(f"Trigger {trigger.name} reached max executions")
                continue

            try:
                await trigger.handler(event)
                trigger.execution_count += 1
                trigger.last_execution = event.timestamp
                _log.info(f"Trigger {trigger.name} executed successfully")

            except Exception as e:  # noqa: BLE001
                _log.error(f"Trigger {trigger.name} failed: {e}")

    def get_event_history(
        self,
        event_type: TriggerEventType | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[TriggerEvent]:
        """Get event history."""
        events = self._event_history

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        if source:
            events = [e for e in events if e.source == source]

        return events[-limit:]

    def get_trigger_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all triggers."""
        stats = {}
        for trigger_id, trigger in self._triggers.items():
            stats[trigger_id] = {
                "name": trigger.name,
                "enabled": trigger.enabled,
                "execution_count": trigger.execution_count,
                "max_executions": trigger.max_executions,
                "last_execution": trigger.last_execution,
                "cooldown_s": trigger.cooldown_s,
            }
        return stats
