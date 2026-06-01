"""Message Channels module for QNMing MoRE OS.

This module provides a unified interface for connecting to various messaging platforms
(Telegram, Discord, Slack, WhatsApp, etc.) similar to Hermes Gateway and OpenFang channels.

Reference: Hermes Gateway, OpenFang channels
"""

from .base import ChannelAdapter, Message, Response
from .manager import ChannelManager
from .telegram_adapter import TelegramAdapter
from .discord_adapter import DiscordAdapter
from .formatter import MessageFormatter
from .wechat_adapter import WeChatAdapter, create_wechat_adapter
from .qq_adapter import QQAdapter, create_qq_adapter
from .webhook_adapter import WebhookAdapter, create_webhook_adapter, WebhookServer

__all__ = [
    "ChannelAdapter",
    "Message",
    "Response",
    "ChannelManager",
    "TelegramAdapter",
    "DiscordAdapter", 
    "MessageFormatter",
    "WeChatAdapter",
    "create_wechat_adapter",
    "QQAdapter",
    "create_qq_adapter",
    "WebhookAdapter",
    "create_webhook_adapter",
    "WebhookServer",
]