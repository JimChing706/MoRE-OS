"""QQ Channel Adapter - 支持 QQ 机器人 (go-cqhttp 兼容)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from dataclasses import dataclass

import httpx

from .base import ChannelAdapter, Response

_log = logging.getLogger(__name__)


@dataclass
class QQConfig:
    """QQ bot configuration."""
    host: str = "127.0.0.1"
    port: int = 5700
    access_token: str = ""
    api_path: str = "/"
    event_handler: Any = None


class QQAdapter(ChannelAdapter):
    """QQ bot adapter compatible with go-cqhttp / NoneBot2."""
    
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._host = config.get("host", "127.0.0.1")
        self._port = config.get("port", 5700)
        self._access_token = config.get("access_token", "")
        self._api_path = config.get("api_path", "/")
        self._session: httpx.AsyncClient | None = None
        self._running = False
        self._event_queue: asyncio.Queue | None = None

    @property
    def platform_name(self) -> str:
        return "qq"

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}{self._api_path}"

    async def start(self) -> None:
        """Start QQ adapter."""
        headers = {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}
        self._session = httpx.AsyncClient(
            headers=headers,
            timeout=30,
        )
        
        try:
            resp = await self._session.get(f"{self.base_url}/get_login_info")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    _log.info(f"QQ bot connected: {data.get('data', {}).get('nickname', 'unknown')}")
        except Exception as e:
            _log.warning(f"QQ bot connection check failed: {e}")
        
        self._running = True
        self._event_queue = asyncio.Queue()
        asyncio.create_task(self._event_loop())

    async def stop(self) -> None:
        """Stop QQ adapter."""
        self._running = False
        if self._session:
            await self._session.aclose()

    async def send_message(self, response: Response) -> bool:
        """Send message via QQ."""
        try:
            chat_id = response.chat_id
            
            if chat_id.startswith("group_"):
                group_id = chat_id.replace("group_", "")
                return await self._send_group_message(int(group_id), response.content)
            elif chat_id.startswith("user_"):
                user_id = chat_id.replace("user_", "")
                return await self._send_private_message(int(user_id), response.content)
            else:
                return await self._send_private_message(int(chat_id), response.content)
        except Exception as e:
            _log.error(f"QQ send failed: {e}")
            return False

    async def _send_private_message(self, user_id: int, content: str) -> bool:
        """Send private message."""
        payload = {
            "user_id": user_id,
            "message": [{"type": "text", "data": {"text": content}}],
        }
        r = await self._session.post(f"{self.base_url}/send_private_msg", json=payload)
        return r.json().get("status") == "ok"

    async def _send_group_message(self, group_id: int, content: str) -> bool:
        """Send group message."""
        payload = {
            "group_id": group_id,
            "message": [{"type": "text", "data": {"text": content}}],
        }
        r = await self._session.post(f"{self.base_url}/send_group_msg", json=payload)
        return r.json().get("status") == "ok"

    async def send_message_to_user(self, content: str, user_id: str) -> bool:
        """Send direct message to user."""
        try:
            return await self._send_private_message(int(user_id), content)
        except Exception:
            return False

    async def _event_loop(self) -> None:
        """Process events (placeholder - requires WebSocket for real-time)."""
        while self._running:
            await asyncio.sleep(1)

    async def health_check(self) -> bool:
        """Check QQ bot status."""
        try:
            r = await self._session.get(f"{self.base_url}/get_login_info")
            return r.json().get("status") == "ok"
        except Exception:
            return False

    async def get_group_list(self) -> list[dict]:
        """Get group list."""
        r = await self._session.get(f"{self.base_url}/get_group_list")
        data = r.json()
        return data.get("data", []) if data.get("status") == "ok" else []

    async def get_friend_list(self) -> list[dict]:
        """Get friend list."""
        r = await self._session.get(f"{self.base_url}/get_friend_list")
        data = r.json()
        return data.get("data", []) if data.get("status") == "ok" else []

    def parse_cq_code(self, message: str) -> list[dict]:
        """Parse CQ code to message segments."""
        import re
        segments = []
        pattern = r'\[CQ:([^,\]]+)(?:,([^\]]+))?\]'
        
        last_end = 0
        for match in re.finditer(pattern, message):
            if match.start() > last_end:
                segments.append({"type": "text", "data": {"text": message[last_end:match.start()]}})
            
            cq_type = match.group(1)
            params = {}
            if match.group(2):
                for param in match.group(2).split(","):
                    if "=" in param:
                        k, v = param.split("=", 1)
                        params[k] = v
            segments.append({"type": cq_type, "data": params})
            last_end = match.end()
        
        if last_end < len(message):
            segments.append({"type": "text", "data": {"text": message[last_end:]}})
        
        return segments


def create_qq_adapter(
    host: str = "127.0.0.1",
    port: int = 5700,
    access_token: str = "",
) -> QQAdapter:
    """Factory for QQ adapter."""
    return QQAdapter({
        "host": host,
        "port": port,
        "access_token": access_token,
    })