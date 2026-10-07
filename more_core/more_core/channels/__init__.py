"""Message Channels module for QNMing MoRE OS.

This module provides a unified interface for connecting to various messaging platforms
(Telegram, Discord, Slack, WhatsApp, etc.) similar to Hermes Gateway and OpenFang channels.

Reference: Hermes Gateway, OpenFang channels
"""

from .base import ChannelAdapter, Message, Response
from .discord_adapter import DiscordAdapter
from .formatter import MessageFormatter
from .manager import ChannelManager
from .qq_adapter import QQAdapter, create_qq_adapter
from .telegram_adapter import TelegramAdapter
from .webhook_adapter import WebhookAdapter, WebhookServer, create_webhook_adapter
from .wechat_adapter import WeChatAdapter, create_wechat_adapter

__all__ = [
    "ChannelAdapter",
    "ChannelManager",
    "DiscordAdapter",
    "Message",
    "MessageFormatter",
    "QQAdapter",
    "Response",
    "TelegramAdapter",
    "WeChatAdapter",
    "WebhookAdapter",
    "WebhookServer",
    "create_qq_adapter",
    "create_webhook_adapter",
    "create_wechat_adapter",
]
