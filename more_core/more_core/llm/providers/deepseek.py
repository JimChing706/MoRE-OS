"""DeepSeek API provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import ClassVar

import httpx

from ...core.errors import LLMError
from ..provider import LLMRequest, LLMResponse


class DeepSeekProvider:
    """DeepSeek API provider - supports DeepSeek Chat and Coder models.

    Uses a persistent httpx.AsyncClient (connection pool + keep-alive)
    instead of creating a new client per request, avoiding a TLS handshake
    and connection setup on every call.
    """

    MODELS: ClassVar[dict[str, str]] = {
        "deepseek-chat": "deepseek-chat",
        "deepseek-coder": "deepseek-coder",
        "deepseek-chat-v2": "deepseek-chat-v2",
        "deepseek-coder-v2": "deepseek-coder-v2",
        "deepseek-chat-v3": "deepseek-chat",
        "deepseek-reasoner": "deepseek-reasoner",
        "deepseek-v3": "deepseek-chat",
    }

    def __init__(
        self,
        name: str,
        api_key: str,
        endpoint: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: int = 120,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base = endpoint.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return the persistent client, creating it lazily."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={"Authorization": f"Bearer {self._api_key}"},
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model_override or self.model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": False,
        }
        if request.enable_thinking:
            payload["thinking"] = {"type": "enabled"}
        try:
            r = await self._get_client().post(
                f"{self._base}/v1/chat/completions",
                json=payload,
            )
        except httpx.ConnectError as e:
            raise LLMError(f"deepseek connection failed: {e}")
        except httpx.ReadTimeout:
            raise LLMError(f"deepseek read timeout after {self._timeout}s")
        if r.status_code >= 400:
            raise LLMError(f"deepseek {r.status_code}: {r.text}")
        data = r.json()
        msg = data["choices"][0]["message"]
        return LLMResponse(
            content=msg["content"],
            provider=self.name,
            model=self.model,
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            reasoning_content=msg.get("reasoning_content"),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        payload = {
            "model": request.model_override or self.model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": True,
        }
        async with self._get_client().stream(
            "POST",
            f"{self._base}/v1/chat/completions",
            json=payload,
        ) as r:
            if r.status_code >= 400:
                raise LLMError(f"deepseek {r.status_code}")
            async for line in r.aiter_lines():
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    try:
                        obj = json.loads(data)
                        chunk = obj["choices"][0].get("delta", {}).get("content")
                        if chunk:
                            yield chunk
                    except Exception:  # noqa: BLE001, S112
                        continue

    async def health(self) -> bool:
        try:
            r = await self._get_client().get(
                f"{self._base}/v1/models",
                timeout=5,
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        """Close the persistent client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_messages(self, request: LLMRequest) -> list[dict[str, str]]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        return messages
