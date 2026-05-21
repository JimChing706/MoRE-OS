"""Telegram Bot adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .base import ChannelAdapter, Message, Response

_log = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API adapter."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._token = config.get("bot_token", "")
        self._api_base = f"https://api.telegram.org/bot{self._token}"
        self._offset = 0
        self._running = False
        self._poll_task: asyncio.Task | None = None

    @property
    def platform_name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """Start polling for updates."""
        me = await self._call_api("getMe")
        if not me.get("ok"):
            raise RuntimeError(f"Telegram bot auth failed: {me}")
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        _log.info("Telegram bot @%s started", me["result"]["username"])

    async def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        _log.info("Telegram bot stopped")

    async def send_message(self, response: Response) -> bool:
        """Send a message via Telegram Bot API."""
        payload = {
            "chat_id": response.chat_id,
            "text": response.content,
            "parse_mode": "Markdown",
        }
        result = await self._call_api("sendMessage", payload)
        return result.get("ok", False)

    async def health_check(self) -> bool:
        """Check if bot is alive."""
        try:
            result = await self._call_api("getMe")
            return result.get("ok", False)
        except Exception:
            return False

    async def _poll_loop(self) -> None:
        """Poll for updates."""
        while self._running:
            try:
                updates = await self._call_api(
                    "getUpdates",
                    {"offset": self._offset, "timeout": 30},
                )
                if updates.get("ok"):
                    for update in updates.get("result", []):
                        await self._handle_update(update)
                        self._offset = update["update_id"] + 1
            except Exception as e:
                _log.error("Telegram poll error: %s", e)
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Handle an incoming update."""
        msg = update.get("message")
        if not msg:
            return
        chat = msg.get("chat", {})
        from_user = msg.get("from", {})
        message = Message(
            id=str(update["update_id"]),
            platform="telegram",
            chat_id=str(chat.get("id", "")),
            user_id=str(from_user.get("id", "")),
            user_name=from_user.get("username", from_user.get("first_name", "Unknown")),
            content=msg.get("text", ""),
            timestamp=time.time(),
            metadata={"message_id": msg.get("message_id")},
        )
        await self._handle_message(message)

    async def _call_api(self, method: str, params: dict | None = None) -> dict:
        """Make a call to the Telegram Bot API."""
        url = f"{self._api_base}/{method}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=params or {})
            return r.json()


def create_telegram_adapter(bot_token: str) -> TelegramAdapter:
    """Factory function to create a Telegram adapter."""
    return TelegramAdapter({"bot_token": bot_token})