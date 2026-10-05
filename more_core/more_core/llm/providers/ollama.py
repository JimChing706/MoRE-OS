"""Ollama local provider (http://host:11434)."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ...core.errors import LLMError
from ..provider import LLMRequest, LLMResponse


class OllamaProvider:
    def __init__(self, name: str, endpoint: str, model: str, timeout: int = 120) -> None:
        self.name = name
        self.model = model
        self._base = endpoint.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=60.0,
                ),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model_override or self.model,
            "prompt": request.prompt,
            "system": request.system,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        client = self._get_client()
        try:
            r = await client.post(f"{self._base}/api/generate", json=payload)
        except httpx.ConnectError:
            raise LLMError(
                f"ollama connection failed at {self._base} (is Ollama running? try: ollama serve)"
            )
        except httpx.ReadTimeout:
            raise LLMError(
                f"ollama read timeout after {self._timeout}s "
                f"(model may still be loading; try again or increase timeout)"
            )
        if r.status_code >= 400:
            raise LLMError(f"ollama {r.status_code}: {r.text}")
        data = r.json()
        return LLMResponse(
            content=data.get("response", ""),
            provider=self.name,
            model=self.model,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        payload = {
            "model": request.model_override or self.model,
            "prompt": request.prompt,
            "system": request.system,
            "stream": True,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        client = self._get_client()
        async with client.stream("POST", f"{self._base}/api/generate", json=payload) as r:
            if r.status_code >= 400:
                raise LLMError(f"ollama {r.status_code}")
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = obj.get("response")
                if chunk:
                    yield chunk
                if obj.get("done"):
                    return

    async def health(self) -> bool:
        try:
            client = self._get_client()
            r = await client.get(f"{self._base}/api/tags")
            return r.status_code == 200
        except Exception:
            return False
