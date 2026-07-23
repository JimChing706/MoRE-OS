"""Discord Bot adapter."""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from .base import ChannelAdapter, Response

_log = logging.getLogger(__name__)


class DiscordAdapter(ChannelAdapter):
    """Discord Bot adapter using HTTP API."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._token = config.get("bot_token", "")
        self._application_id = config.get("application_id", "")
        self._guild_id = config.get("guild_id", "")
        self._session: httpx.AsyncClient | None = None
        self._running = False

    @property
    def platform_name(self) -> str:
        return "discord"

    async def start(self) -> None:
        """Start the Discord bot."""
        self._session = httpx.AsyncClient(
            headers={
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        me = await self._call_api("GET", "/users/@me")
        if "id" not in me:
            raise RuntimeError(f"Discord bot auth failed: {me}")
        self._running = True
        _log.info("Discord bot %s started (app_id=%s)", me.get("username"), self._application_id)
        _log.info(
            "To add bot to server: https://discord.com/oauth2/authorize?client_id=%s&permissions=0&scope=bot",
            self._application_id,
        )

    async def stop(self) -> None:
        """Stop the Discord bot."""
        self._running = False
        if self._session:
            await self._session.aclose()
        _log.info("Discord bot stopped")

    async def send_message(self, response: Response) -> bool:
        """Send a message via Discord API."""
        channel_id = response.chat_id
        payload = {"content": response.content}
        result = await self._call_api("POST", f"/channels/{channel_id}/messages", payload)
        return "id" in result

    async def health_check(self) -> bool:
        """Check if bot is alive."""
        try:
            me = await self._call_api("GET", "/users/@me")
            return "id" in me
        except Exception:
            return False

    async def _call_api(
        self, method: str, endpoint: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a call to the Discord API."""
        assert self._session is not None
        url = f"https://discord.com/api/v10{endpoint}"
        r = await self._session.request(method, url, json=data)
        if r.status_code >= 400:
            raise RuntimeError(f"Discord API error: {r.status_code} {r.text}")
        return cast(dict[str, Any], r.json())


def create_discord_adapter(
    bot_token: str, application_id: str = "", guild_id: str = ""
) -> DiscordAdapter:
    """Factory function to create a Discord adapter."""
    return DiscordAdapter(
        {
            "bot_token": bot_token,
            "application_id": application_id,
            "guild_id": guild_id,
        }
    )
