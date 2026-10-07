"""WeChat (微信) Channel Adapter - 支持企业微信和个人微信 webhook."""

from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from .base import ChannelAdapter, Message, Response

_log = logging.getLogger(__name__)


@dataclass
class WeChatConfig:
    """WeChat configuration."""

    corp_id: str = ""
    agent_id: str = ""
    secret: str = ""
    token: str = ""
    encoding_aes_key: str = ""
    webhook_url: str = ""


class WeChatAdapter(ChannelAdapter):
    """WeChat Work (企业微信) and WeCom webhook adapter."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._corp_id = config.get("corp_id", "")
        self._agent_id = config.get("agent_id", "")
        self._secret = config.get("secret", "")
        self._token = config.get("token", "")
        self._webhook_url = config.get("webhook_url", "")
        self._access_token: str | None = None
        self._token_expires: float = 0
        self._session: httpx.AsyncClient | None = None
        self._running = False

    @property
    def platform_name(self) -> str:
        return "wechat"

    async def start(self) -> None:
        """Start WeChat adapter."""
        self._session = httpx.AsyncClient(timeout=30)
        if self._webhook_url:
            _log.info(f"WeChat webhook adapter ready: {self._webhook_url}")
        else:
            await self._get_access_token()
        self._running = True

    async def stop(self) -> None:
        """Stop WeChat adapter."""
        self._running = False
        if self._session:
            await self._session.aclose()

    async def send_message(self, response: Response) -> bool:
        """Send message via WeChat."""
        try:
            if self._webhook_url:
                return await self._send_webhook(response)
            else:
                return await self._send_work_message(response)
        except Exception as e:  # noqa: BLE001
            _log.error(f"WeChat send failed: {e}")
            return False

    async def _send_webhook(self, response: Response) -> bool:
        """Send via webhook (支持自定义机器人)."""
        assert self._session is not None
        payload = {
            "msgtype": "text",
            "text": {"content": response.content},
        }
        r = await self._session.post(self._webhook_url, json=payload)
        return r.status_code == 200

    async def _send_work_message(self, response: Response) -> bool:
        """Send via WeChat Work API."""
        assert self._session is not None
        if not self._access_token:
            await self._get_access_token()

        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={self._access_token}"
        payload = {
            "touser": "@all",
            "msgtype": "text",
            "agentid": self._agent_id,
            "text": {"content": response.content},
        }
        r = await self._session.post(url, json=payload)
        data: Any = r.json()
        return bool(data.get("errcode", 0) == 0)

    async def _get_access_token(self) -> None:
        """Get WeChat Work access token."""
        assert self._session is not None
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self._corp_id}&corpsecret={self._secret}"
        r = await self._session.get(url)
        data: Any = r.json()
        if data.get("errcode") == 0:
            self._access_token = data.get("access_token")
            self._token_expires = time.time() + data.get("expires_in", 7200)

    async def health_check(self) -> bool:
        """Check WeChat connection."""
        try:
            if self._webhook_url:
                return True
            if time.time() > self._token_expires:
                await self._get_access_token()
            return bool(self._access_token)
        except Exception:  # noqa: BLE001
            return False

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        """Verify WeChat webhook signature."""
        if not self._token:
            return True
        sorted_list = sorted([self._token, timestamp, nonce])
        sign = hashlib.sha1("".join(sorted_list).encode()).hexdigest()
        return signature == sign

    async def parse_webhook(self, body: bytes) -> Message | None:
        """Parse WeChat webhook event."""
        try:
            root = ET.fromstring(body)
            msg_type_elem = root.find("MsgType")
            msg_type = (msg_type_elem.text or "") if msg_type_elem is not None else ""

            if msg_type == "text":
                msg_id_elem = root.find("MsgId")
                from_user_elem = root.find("FromUserName")
                content_elem = root.find("Content")
                return Message(
                    id=(msg_id_elem.text or "") if msg_id_elem is not None else "",
                    platform="wechat",
                    chat_id=(from_user_elem.text or "") if from_user_elem is not None else "",
                    user_id=(from_user_elem.text or "") if from_user_elem is not None else "",
                    user_name=(from_user_elem.text or "") if from_user_elem is not None else "",
                    content=(content_elem.text or "") if content_elem is not None else "",
                    timestamp=time.time(),
                    metadata={"raw": body.decode()},
                )
        except Exception as e:  # noqa: BLE001
            _log.error(f"Failed to parse webhook: {e}")
        return None


def create_wechat_adapter(
    webhook_url: str = "",
    corp_id: str = "",
    agent_id: str = "",
    secret: str = "",
) -> WeChatAdapter:
    """Factory for WeChat adapter."""
    return WeChatAdapter(
        {
            "webhook_url": webhook_url,
            "corp_id": corp_id,
            "agent_id": agent_id,
            "secret": secret,
        }
    )
