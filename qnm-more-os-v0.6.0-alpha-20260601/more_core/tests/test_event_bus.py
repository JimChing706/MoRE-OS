import asyncio

import pytest

from more_core.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_publish_subscribe_delivers_events() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event):  # type: ignore[no-untyped-def]
        received.append(event.data)

    bus.subscribe("t", handler)
    await bus.start()
    try:
        await bus.publish("t", "hello")
        await asyncio.sleep(0.05)
    finally:
        await bus.stop()

    assert received == ["hello"]


@pytest.mark.asyncio
async def test_wildcard_subscriber() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def any_handler(event):  # type: ignore[no-untyped-def]
        seen.append(event.topic)

    bus.subscribe("*", any_handler)
    await bus.start()
    try:
        await bus.publish("a")
        await bus.publish("b")
        await asyncio.sleep(0.05)
    finally:
        await bus.stop()

    assert set(seen) == {"a", "b"}
