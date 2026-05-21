"""HTTP/Webhook channel adapter."""

from __future__ import annotations

import logging
from typing import Any

from .base import ChannelAdapter, ChannelConfig, ChannelMessage, ChannelType, ChannelUser

_log = logging.getLogger(__name__)


class HTTPChannelAdapter(ChannelAdapter):
    """HTTP/Webhook channel adapter for custom integrations."""
    
    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._session: Any = None
    
    async def start(self) -> None:
        """Start HTTP adapter."""
        await super().start()
        
        try:
            import aiohttp
            self._session = aiohttp.ClientSession()
            _log.info("HTTP channel adapter started")
        except ImportError:
            _log.warning("aiohttp not installed, HTTP channel unavailable")
    
    async def stop(self) -> None:
        """Stop HTTP adapter."""
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
        """Send message via HTTP webhook."""
        if not self.config.webhook_url:
            raise RuntimeError("Webhook URL not configured")

        payload = {
            "content": content,
            "channel_id": channel_id,
            "user_id": user_id,
            "reply_to": reply_to,
        }

        async with self._session.post(self.config.webhook_url, json=payload) as response:
            if response.status >= 400:
                _log.error(f"Webhook error: {response.status}")
                return ""
            
            result = await response.json()
            return result.get("message_id", "")
    
    async def send_message_to_user(self, content: str, user_id: str) -> str:
        """Send message to user via webhook."""
        return await self.send_message(content, channel_id=user_id, user_id=user_id)
    
    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit message via webhook."""
        if not self.config.webhook_url:
            return False

        payload = {
            "action": "edit",
            "message_id": message_id,
            "content": new_content,
        }

        async with self._session.post(self.config.webhook_url, json=payload) as response:
            return response.status < 400

    async def delete_message(self, message_id: str) -> bool:
        """Delete message via webhook."""
        if not self.config.webhook_url:
            return False
        
        payload = {
            "action": "delete",
            "message_id": message_id,
        }
        
        async with self._session.post(self._config.webhook_url, json=payload) as response:
            return response.status < 400
    
    async def get_user_info(self, user_id: str) -> ChannelUser | None:
        """Get user info via webhook."""
        if not self.config.webhook_url:
            return None

        try:
            async with self._session.get(
                f"{self.config.webhook_url}/user/{user_id}"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return ChannelUser(
                        id=data.get("id", user_id),
                        name=data.get("name", user_id),
                        username=data.get("username"),
                    )
        except Exception as e:
            _log.error(f"Failed to get user info: {e}")
        
        return None
    
    async def process_webhook(self, payload: dict[str, Any]) -> None:
        """Process incoming webhook."""
        message = ChannelMessage(
            message_id=payload.get("message_id", ""),
            channel_type=ChannelType.WEBHOOK,
            channel_id=payload.get("channel_id", ""),
            user=ChannelUser(
                id=payload.get("user_id", "unknown"),
                name=payload.get("user_name", "Unknown"),
            ),
            content=payload.get("content", ""),
            raw_data=payload,
        )
        
        await self.handle_incoming_message(message)


class WebhookServer:
    """Simple webhook server for receiving messages."""
    
    def __init__(self, adapter: HTTPChannelAdapter, host: str = "0.0.0.0", port: int = 8080) -> None:
        self._adapter = adapter
        self._host = host
        self._port = port
        self._running = False
        self._app: Any = None
        self._web: Any = None
    
    async def start(self) -> None:
        """Start webhook server."""
        try:
            from aiohttp import web as aiohttp_web
            self._web = aiohttp_web
            self._app = aiohttp_web.Application()
            self._app.router.add_post("/webhook", self._handle_webhook)
            self._app.router.add_get("/health", self._health_check)
            
            runner = aiohttp_web.AppRunner(self._app)
            await runner.setup()
            
            site = aiohttp_web.TCPSite(runner, self._host, self._port)
            await site.start()
            
            self._running = True
            _log.info("Webhook server started on %s:%d", self._host, self._port)
        except ImportError:
            _log.warning("aiohttp not installed, webhook server unavailable")
    
    async def stop(self) -> None:
        """Stop webhook server."""
        self._running = False
    
    async def _handle_webhook(self, request: Any) -> Any:
        """Handle incoming webhook request."""
        try:
            payload = await request.json()
            await self._adapter.process_webhook(payload)
            return self._web.json_response({"status": "ok"})
        except Exception as e:
            _log.error("Webhook error: %s", e)
            return self._web.json_response({"status": "error"}, status=500)
    
    async def _health_check(self, request: Any) -> Any:
        """Health check endpoint."""
        return self._web.json_response({"status": "healthy"})


def create_http_adapter(webhook_url: str) -> HTTPChannelAdapter:
    """Create HTTP/Webhook adapter."""
    config = ChannelConfig(
        channel_type=ChannelType.WEBHOOK,
        enabled=True,
        webhook_url=webhook_url,
    )
    return HTTPChannelAdapter(config)