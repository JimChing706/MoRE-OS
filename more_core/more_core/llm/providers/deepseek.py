"""DeepSeek API provider."""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from ...core.errors import LLMError
from ..provider import LLMRequest, LLMResponse


class DeepSeekProvider:
    """DeepSeek API provider - supports DeepSeek Chat and Coder models."""

    MODELS = {
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

    async def generate(self, request: LLMRequest) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": False,
        }
        if request.enable_thinking:
            payload["thinking"] = {"type": "enabled"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(
                    f"{self._base}/v1/chat/completions",
                    json=payload,
                    headers=headers,
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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 4096,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as r:
                if r.status_code >= 400:
                    raise LLMError(f"deepseek {r.status_code}")
                async for line in r.aiter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            import json

                            obj = json.loads(data)
                            chunk = obj["choices"][0].get("delta", {}).get("content")
                            if chunk:
                                yield chunk
                        except Exception:
                            continue

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{self._base}/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return r.status_code == 200
        except Exception:
            return False

    def _build_messages(self, request: LLMRequest) -> list[dict[str, str]]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        return messages
