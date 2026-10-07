"""Webhook Channel Adapter - 通用 HTTP Webhook 支持."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from .base import ChannelAdapter, Response

_log = logging.getLogger(__name__)


class WebhookMethod(Enum):
    """Webhook HTTP methods."""

    POST = "POST"
    GET = "GET"
    PUT = "PUT"


@dataclass
class WebhookConfig:
    """Webhook configuration."""

    url: str = ""
    method: str = "POST"
    headers: dict[str, Any] | None = None
    secret: str = ""
    verify_ssl: bool = True
    timeout: int = 30


class WebhookAdapter(ChannelAdapter):
    """Generic webhook adapter for REST callbacks."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._url = config.get("url", "")
        self._method = WebhookMethod(config.get("method", "POST"))
        self._headers = config.get("headers", {"Content-Type": "application/json"})
        self._secret = config.get("secret", "")
        self._verify_ssl = config.get("verify_ssl", True)
        self._timeout = config.get("timeout", 30)
        self._session: httpx.AsyncClient | None = None
        self._running = False
        self._stats = {
            "sent": 0,
            "failed": 0,
            "last_sent": 0.0,
        }

    @property
    def platform_name(self) -> str:
        return "webhook"

    async def start(self) -> None:
        """Start webhook adapter."""
        self._session = httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        self._running = True
        _log.info(f"Webhook adapter ready: {self._url}")

    async def stop(self) -> None:
        """Stop webhook adapter."""
        self._running = False
        if self._session:
            await self._session.aclose()

    async def send_message(self, response: Response) -> bool:
        """Send message via webhook."""
        assert self._session is not None
        try:
            payload = {
                "content": response.content,
                "chat_id": response.chat_id,
                "metadata": response.metadata or {},
                "timestamp": time.time(),
            }

            headers = dict(self._headers)
            if self._secret:
                payload["signature"] = self._generate_signature(json.dumps(payload))
                headers["X-Signature"] = payload["signature"]

            r = await self._session.request(
                self._method.value,
                self._url,
                json=payload,
                headers=headers,
            )

            if r.status_code >= 200 and r.status_code < 300:
                self._stats["sent"] += 1
                self._stats["last_sent"] = time.time()
                return True
            else:
                self._stats["failed"] += 1
                _log.warning(f"Webhook failed: {r.status_code} {r.text}")
                return False

        except Exception as e:  # noqa: BLE001
            self._stats["failed"] += 1
            _log.error(f"Webhook error: {e}")
            return False

    async def send_message_to_user(self, content: str, user_id: str) -> bool:
        """Send to specific user (via webhook)."""
        return await self.send_message(
            Response(
                content=content,
                chat_id=user_id,
                metadata={"type": "direct"},
            )
        )

    def _generate_signature(self, data: str) -> str:
        """Generate HMAC signature."""
        if not self._secret:
            return ""
        return hmac.new(
            self._secret.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def health_check(self) -> bool:
        """Check webhook endpoint."""
        assert self._session is not None
        if not self._url:
            return False
        try:
            if self._method == WebhookMethod.GET:
                r = await self._session.get(self._url)
            else:
                r = await self._session.head(self._url)
            return r.status_code < 400
        except Exception:  # noqa: BLE001
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get webhook statistics."""
        return dict(self._stats)

    async def test_connection(self) -> dict[str, Any]:
        """Test webhook with sample payload."""
        test_payload = {
            "action": "test",
            "timestamp": time.time(),
            "content": "Test message from MoRE OS",
        }

        assert self._session is not None
        try:
            headers = dict(self._headers)
            if self._secret:
                test_payload["signature"] = self._generate_signature(json.dumps(test_payload))

            r = await self._session.post(
                self._url,
                json=test_payload,
                headers=headers,
            )

            return {
                "success": r.status_code >= 200 and r.status_code < 300,
                "status_code": r.status_code,
                "response": r.text[:200],
            }
        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": str(e),
            }


def create_webhook_adapter(
    url: str,
    method: str = "POST",
    secret: str = "",
    headers: dict[str, Any] | None = None,
) -> WebhookAdapter:
    """Factory for webhook adapter."""
    return WebhookAdapter(
        {
            "url": url,
            "method": method,
            "secret": secret,
            "headers": headers or {"Content-Type": "application/json"},
        }
    )


class WebhookServer:
    """Simple webhook server for receiving callbacks."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self._host = host
        self._port = port
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._server = None

    def register_handler(self, path: str, handler: Callable[..., Any]) -> None:
        """Register webhook handler."""
        self._handlers[path] = handler

    async def handle_request(
        self, path: str, body: bytes, headers: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle incoming webhook request."""
        handler = self._handlers.get(path)
        if not handler:
            return {"status": 404, "body": "Not found"}

        try:
            import json

            data = json.loads(body) if body else {}
            result = await handler(data, headers)
            return {"status": 200, "body": result}
        except Exception as e:  # noqa: BLE001
            return {"status": 500, "body": str(e)}

    async def start(self) -> None:
        """Start webhook server (requires aiohttp or similar)."""
        _log.info(f"Webhook server would start on {self._host}:{self._port}")
        _log.info(f"Registered paths: {list(self._handlers.keys())}")
