"""Discord channel adapter."""

from __future__ import annotations

import logging
from typing import Any

from .base import ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, ChannelUser

_log = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapter):
    """Discord bot adapter."""
    
    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._api_url = "https://discord.com/api/v10"
        self._session: Any = None
    
    async def start(self) -> None:
        """Start Discord adapter."""
        await super().start()
        
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bot {self.config.bot_token}",
                    "Content-Type": "application/json",
                }
            )
            
            me = await self._make_request("GET", "/users/@me")
            _log.info(f"Discord bot started: {me.get('username')}")
        except ImportError:
            _log.warning("aiohttp not installed, Discord unavailable")
        except Exception as e:
            _log.error(f"Failed to start Discord: {e}")
    
    async def stop(self) -> None:
        """Stop Discord adapter."""
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
        """Send message to Discord channel."""
        payload = {"content": content}
        
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}
        
        result = await self._make_request("POST", f"/channels/{channel_id}/messages", payload)
        return result.get("id", "")
    
    async def send_message_to_user(self, content: str, user_id: str) -> str:
        """Send direct message to user."""
        dm_channel = await self._make_request(
            "POST",
            "/users/@me/channels",
            {"recipient_id": user_id}
        )
        channel_id = dm_channel.get("id", "")
        return await self.send_message(content, channel_id)
    
    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit Discord message."""
        parts = message_id.split(":")
        if len(parts) < 2:
            return False
        
        channel_id, msg_id = parts[0], parts[1]
        
        await self._make_request(
            "PATCH",
            f"/channels/{channel_id}/messages/{msg_id}",
            {"content": new_content}
        )
        return True
    
    async def delete_message(self, message_id: str) -> bool:
        """Delete Discord message."""
        parts = message_id.split(":")
        if len(parts) < 2:
            return False
        
        channel_id, msg_id = parts[0], parts[1]
        
        await self._make_request("DELETE", f"/channels/{channel_id}/messages/{msg_id}")
        return True
    
    async def get_user_info(self, user_id: str) -> ChannelUser | None:
        """Get Discord user info."""
        try:
            user = await self._make_request("GET", f"/users/{user_id}")
            return ChannelUser(
                id=user.get("id", ""),
                name=user.get("global_name") or user.get("username", ""),
                username=user.get("username"),
            )
        except Exception as e:
            _log.error(f"Failed to get user info: {e}")
            return None
    
    async def process_webhook(self, payload: dict[str, Any]) -> None:
        """Process Discord webhook/interaction."""
        if payload.get("type") == 1:
            return
        
        if "message" in payload:
            msg = payload["message"]
            author = msg.get("author", {})
            
            message = ChannelMessage(
                message_id=str(msg.get("id", "")),
                channel_type=ChannelType.DISCORD,
                channel_id=str(payload.get("channel_id", "")),
                user=ChannelUser(
                    id=str(author.get("id", "")),
                    name=author.get("global_name") or author.get("username", ""),
                    username=author.get("username"),
                ),
                content=msg.get("content", ""),
                raw_data=msg,
            )
            
            await self.handle_incoming_message(message)
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make API request to Discord."""
        if not self._session:
            raise RuntimeError("Discord session not initialized")
        
        url = f"{self._api_url}{endpoint}"
        
        async with self._session.request(method, url, json=data) as response:
            if response.status == 204:
                return {}
            
            result = await response.json()
            if response.status >= 400:
                raise Exception(result.get("message", "API error"))
            
            return result


def create_discord_adapter(bot_token: str) -> DiscordAdapter:
    """Create Discord adapter with bot token."""
    config = ChannelConfig(
        channel_type=ChannelType.DISCORD,
        enabled=True,
        bot_token=bot_token,
    )
    return DiscordAdapter(config)