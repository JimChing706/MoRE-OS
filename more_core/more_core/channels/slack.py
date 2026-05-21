"""Slack channel adapter."""

from __future__ import annotations

import logging
from typing import Any

from .base import ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, ChannelUser

_log = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack bot adapter."""
    
    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._api_url = "https://slack.com/api"
        self._session: Any = None
    
    async def start(self) -> None:
        """Start Slack adapter."""
        await super().start()
        
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.config.bot_token}",
                    "Content-Type": "application/json",
                }
            )
            
            result = await self._make_request("auth.test")
            _log.info(f"Slack bot started: {result.get('user')}")
        except ImportError:
            _log.warning("aiohttp not installed, Slack unavailable")
        except Exception as e:
            _log.error(f"Failed to start Slack: {e}")
    
    async def stop(self) -> None:
        """Stop Slack adapter."""
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
        """Send message to Slack channel."""
        payload = {
            "channel": channel_id,
            "text": content,
        }
        
        if reply_to:
            payload["thread_ts"] = reply_to
        
        result = await self._make_request("chat.postMessage", payload)
        return result.get("ts", "")
    
    async def send_message_to_user(self, content: str, user_id: str) -> str:
        """Send direct message to user."""
        return await self.send_message(content, channel_id=user_id)
    
    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit Slack message."""
        parts = message_id.split(":")
        if len(parts) < 2:
            return False
        
        channel_id, ts = parts[0], parts[1]
        
        result = await self._make_request("chat.update", {
            "channel": channel_id,
            "ts": ts,
            "text": new_content,
        })
        return result.get("ok", False)
    
    async def delete_message(self, message_id: str) -> bool:
        """Delete Slack message."""
        parts = message_id.split(":")
        if len(parts) < 2:
            return False
        
        channel_id, ts = parts[0], parts[1]
        
        result = await self._make_request("chat.delete", {
            "channel": channel_id,
            "ts": ts,
        })
        return result.get("ok", False)
    
    async def get_user_info(self, user_id: str) -> ChannelUser | None:
        """Get Slack user info."""
        try:
            user = await self._make_request("users.info", {"user": user_id})
            if user.get("ok"):
                profile = user.get("user", {}).get("profile", {})
                return ChannelUser(
                    id=user_id,
                    name=profile.get("real_name") or user.get("user", {}).get("name", ""),
                    username=profile.get("display_name") or user.get("user", {}).get("name"),
                )
        except Exception as e:
            _log.error(f"Failed to get user info: {e}")
        return None
    
    async def process_webhook(self, payload: dict[str, Any]) -> None:
        """Process Slack webhook event."""
        if "event" in payload:
            event = payload["event"]
            
            if event.get("type") == "message":
                user = event.get("user", {})
                
                message = ChannelMessage(
                    message_id=event.get("ts", ""),
                    channel_type=ChannelType.SLACK,
                    channel_id=event.get("channel", ""),
                    user=ChannelUser(
                        id=user,
                        name=user,
                    ),
                    content=event.get("text", ""),
                    raw_data=event,
                    reply_to=event.get("thread_ts"),
                )
                
                await self.handle_incoming_message(message)
    
    async def _make_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make API request to Slack."""
        if not self._session:
            raise RuntimeError("Slack session not initialized")
        
        url = f"{self._api_url}/{method}"
        
        async with self._session.post(url, json=params or {}) as response:
            result = await response.json()
            if not result.get("ok"):
                _log.warning(f"Slack API error: {result}")
            return result


def create_slack_adapter(bot_token: str) -> SlackAdapter:
    """Create Slack adapter with bot token."""
    config = ChannelConfig(
        channel_type=ChannelType.SLACK,
        enabled=True,
        bot_token=bot_token,
    )
    return SlackAdapter(config)