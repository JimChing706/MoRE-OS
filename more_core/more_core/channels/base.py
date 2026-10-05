"""Message Channel Base - Abstract adapter for multi-platform messaging."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Callable, Awaitable


class ChannelType(Enum):
    """Supported messaging channel types."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"
    CONSOLE = "console"


@dataclass
class ChannelConfig:
    """Configuration for a channel adapter."""

    channel_type: ChannelType
    enabled: bool = True
    bot_token: str | None = None
    webhook_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelUser:
    """Unified user representation across channels."""

    id: str
    name: str = ""
    username: str | None = None


@dataclass
class ChannelMessage:
    """Unified incoming message representation across channels."""

    message_id: str
    channel_type: ChannelType
    channel_id: str
    user: ChannelUser
    content: str = ""
    raw_data: dict[str, Any] | None = None
    timestamp: float = 0
    reply_to: str | None = None
    attachments: list[MediaAttachment] = field(default_factory=list)


class MediaType(Enum):
    """Supported media types in messages."""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    STICKER = "sticker"
    VOICE = "voice"


@dataclass
class MediaAttachment:
    """A media attachment in a message."""

    type: MediaType
    url: str | None = None
    data: bytes | None = None
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    caption: str = ""


@dataclass
class Message:
    """Unified message format across all channels."""

    id: str
    platform: str
    chat_id: str
    user_id: str
    user_name: str
    content: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)
    # Media support (OpenFang v0.6.6)
    attachments: list[MediaAttachment] = field(default_factory=list)
    reply_to: str | None = None
    thread_id: str | None = None


@dataclass
class Response:
    """Response to be sent back to the user."""

    content: str
    chat_id: str
    metadata: dict[str, Any] | None = None
    # Media support
    attachments: list[MediaAttachment] = field(default_factory=list)
    reply_to: str | None = None


MessageHandler = Callable[[Message], Awaitable[Response | None]]


class ChannelAdapter(ABC):
    """Abstract base class for message channel adapters."""

    def __init__(self, config: ChannelConfig | dict[str, Any]):
        if isinstance(config, dict):
            # 修复 D-17：各适配器会传入平台专有键（url / bot_token / port …），
            # 旧实现直接 ChannelConfig(**config) → TypeError，导致适配器**无法用
            # 真实配置构造**。现在把专有键收进 config.extra，其余照常构造。
            data = dict(config)
            known = {f.name for f in fields(ChannelConfig)}
            extras = {k: v for k, v in data.items() if k not in known}
            base_kwargs = {k: v for k, v in data.items() if k in known}
            merged_extra = {**(base_kwargs.get("extra") or {}), **extras}
            if merged_extra:
                base_kwargs["extra"] = merged_extra
            self.config = ChannelConfig(**base_kwargs)
        else:
            self.config = config
        # 保留原始 dict 供适配器读取自身键（url / method / port ...）
        self.raw_config: dict[str, Any] = dict(config) if isinstance(config, dict) else {}
        self._handler: MessageHandler | None = None

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the adapter and connect to the platform."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter and disconnect from the platform."""
        pass

    @abstractmethod
    async def send_message(self, response: Response) -> bool:
        """Send a response message to the platform."""
        pass

    def set_handler(self, handler: MessageHandler) -> None:
        """Set the message handler callback."""
        self._handler = handler

    async def handle_incoming_message(self, message: ChannelMessage) -> None:
        """Handle an incoming message from the channel.

        Converts ChannelMessage to Message and passes to the registered handler.
        """
        msg = Message(
            id=message.message_id,
            platform=message.channel_type.value,
            chat_id=message.channel_id,
            user_id=message.user.id,
            user_name=message.user.name,
            content=message.content,
            timestamp=message.timestamp or time.time(),
            reply_to=message.reply_to,
            attachments=message.attachments,
        )
        await self._handle_message(msg)

    async def _handle_message(self, message: Message) -> None:
        """Internal handler that calls the user-defined handler."""
        if self._handler:
            response = await self._handler(message)
            if response:
                await self.send_message(response)

    async def health_check(self) -> bool:
        """Check if the adapter is healthy."""
        return True
