"""Telegram channel adapter."""

from __future__ import annotations

import logging
from typing import Any

from .base import ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, ChannelUser

_log = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Telegram bot adapter."""
    
    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._api_url = "https://api.telegram.org"
        self._session: Any = None
    
    @property
    def platform_name(self) -> str:
        return "telegram"
    
    async def start(self) -> None:
        """Start Telegram adapter."""
        await super().start()
        
        try:
            import aiohttp
            self._session = aiohttp.ClientSession()
            
            me = await self._make_request("getMe")
            _log.info(f"Telegram bot started: @{me.get('username')}")
        except ImportError:
            _log.warning("aiohttp not installed, Telegram unavailable")
        except Exception as e:
            _log.error(f"Failed to start Telegram: {e}")
    
    async def stop(self) -> None:
        """Stop Telegram adapter."""
        await super().stop()
        if self._session:
            await self._session.close()
    
    async def send_message(
        self,
        content: str,
        channel_id: str,
        user_id: str | None = None,
        reply_to: str | None = None,
    ) -> str:
        """Send message to Telegram chat."""
        params = {
            "chat_id": channel_id,
            "text": content,
        }
        if reply_to:
            params["reply_to_message_id"] = reply_to
        
        result = await self._make_request("sendMessage", params)
        return str(result.get("message_id", ""))
    
    async def send_message_to_user(self, content: str, user_id: str) -> str:
        """Send direct message to user."""
        return await self.send_message(content, channel_id=user_id)
    
    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit Telegram message."""
        params = {
            "chat_id": message_id.split(":")[0] if ":" in message_id else "",
            "message_id": int(message_id.split(":")[-1]) if ":" in message_id else int(message_id),
            "text": new_content,
        }
        result = await self._make_request("editMessageText", params)
        return "ok" in result
    
    async def delete_message(self, message_id: str) -> bool:
        """Delete Telegram message."""
        parts = message_id.split(":")
        params = {
            "chat_id": parts[0] if parts else "",
            "message_id": int(parts[-1]) if parts else 0,
        }
        result = await self._make_request("deleteMessage", params)
        return "ok" in result
    
    async def get_user_info(self, user_id: str) -> ChannelUser | None:
        """Get Telegram user info."""
        try:
            result = await self._make_request("getChatMember", {
                "chat_id": user_id,
                "user_id": user_id,
            })
            user_data = result.get("user", {})
            return ChannelUser(
                id=str(user_data.get("id", "")),
                name=user_data.get("first_name", ""),
                username=user_data.get("username"),
            )
        except Exception as e:
            _log.error(f"Failed to get user info: {e}")
            return None
    
    async def process_webhook(self, payload: dict[str, Any]) -> None:
        """Process Telegram webhook update."""
        if "message" not in payload:
            return
        
        msg = payload["message"]
        user_data = msg.get("from", {})
        
        message = ChannelMessage(
            message_id=str(msg.get("message_id", "")),
            channel_type=ChannelType.TELEGRAM,
            channel_id=str(msg.get("chat", {}).get("id", "")),
            user=ChannelUser(
                id=str(user_data.get("id", "")),
                name=user_data.get("first_name", ""),
                username=user_data.get("username"),
            ),
            content=msg.get("text", ""),
            raw_data=msg,
            timestamp=msg.get("date", 0),
        )
        
        await self.handle_incoming_message(message)
    
    async def _make_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make API request to Telegram."""
        if not self._session or not self.config.bot_token:
            raise RuntimeError("Telegram session not initialized")

        url = f"{self._api_url}/bot{self.config.bot_token}/{method}"
        async with self._session.post(url, json=params or {}) as response:
            result = await response.json()
            if not result.get("ok"):
                raise Exception(result.get("description", "Unknown error"))
            return result.get("result", {})


def create_telegram_adapter(bot_token: str) -> TelegramAdapter:
    """Create Telegram adapter with token."""
    config = ChannelConfig(
        channel_type=ChannelType.TELEGRAM,
        enabled=True,
        bot_token=bot_token,
    )
    return TelegramAdapter(config)