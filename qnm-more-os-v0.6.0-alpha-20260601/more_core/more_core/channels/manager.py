"""Channel Manager - coordinates all channel adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

from .base import ChannelAdapter, Message, Response

_log = logging.getLogger(__name__)


@dataclass
class ChannelStatus:
    """Status of a channel."""
    channel_name: str
    enabled: bool
    running: bool
    messages_processed: int = 0
    errors: int = 0
    last_error: str | None = None


class ChannelManager:
    """Manages all channel adapters."""
    
    def __init__(self) -> None:
        self._channels: dict[str, ChannelAdapter] = {}
        self._global_handler: Callable[[Message], Awaitable[Response | None]] | None = None
        self._channel_handlers: dict[str, Callable[[Message], Awaitable[Response | None]]] = {}
        self._running = False
    
    def register_channel(self, name: str, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        self._channels[name] = adapter
        adapter.set_handler(self._create_handler(name))
        _log.info(f"Registered channel: {name}")
    
    def unregister_channel(self, name: str) -> None:
        """Unregister a channel adapter."""
        if name in self._channels:
            self._channels.pop(name)
            _log.info("Unregistered channel: %s", name)
    
    def get_channel(self, name: str) -> ChannelAdapter | None:
        """Get a channel adapter."""
        return self._channels.get(name)
    
    def set_global_handler(self, handler: Callable[[Message], Awaitable[Response | None]]) -> None:
        """Set global message handler for all channels."""
        self._global_handler = handler
    
    def set_channel_handler(
        self,
        name: str,
        handler: Callable[[Message], Awaitable[Response | None]],
    ) -> None:
        """Set message handler for specific channel."""
        self._channel_handlers[name] = handler
    
    def _create_handler(self, name: str) -> Callable[[Message], Awaitable[Response | None]]:
        """Create message handler for a channel."""
        async def handler(message: Message):
            if name in self._channel_handlers:
                return await self._channel_handlers[name](message)
            elif self._global_handler:
                return await self._global_handler(message)
            return None
        return handler
    
    async def start_all(self) -> None:
        """Start all registered channels."""
        self._running = True
        for name, adapter in self._channels.items():
            try:
                await adapter.start()
            except Exception as e:
                _log.error(f"Failed to start channel {name}: {e}")
    
    async def stop_all(self) -> None:
        """Stop all registered channels."""
        self._running = False
        for name, adapter in self._channels.items():
            try:
                await adapter.stop()
            except Exception as e:
                _log.error(f"Failed to stop channel {name}: {e}")
    
    async def send_message(
        self,
        channel_name: str,
        content: str,
        chat_id: str,
    ) -> bool:
        """Send message through a specific channel."""
        adapter = self._channels.get(channel_name)
        if not adapter:
            _log.error(f"Channel not found: {channel_name}")
            return False
        
        try:
            response = Response(content=content, chat_id=chat_id)
            return await adapter.send_message(response)
        except Exception as e:
            _log.error(f"Failed to send message: {e}")
            return False
    
    def get_status(self) -> dict[str, ChannelStatus]:
        """Get status of all channels."""
        status = {}
        for name, adapter in self._channels.items():
            status[name] = ChannelStatus(
                channel_name=name,
                enabled=True,
                running=adapter.platform_name != "",
            )
        return status
    
    def list_channels(self) -> list[str]:
        """List all registered channel names."""
        return list(self._channels.keys())
    
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running