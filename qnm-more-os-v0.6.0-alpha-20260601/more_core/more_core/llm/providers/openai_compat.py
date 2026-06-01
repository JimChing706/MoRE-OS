"""OpenAI-compatible provider (OpenAI, DeepSeek, Kimi, Zhipu, vLLM, …)."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ...core.errors import LLMError
from ..provider import LLMRequest, LLMResponse


class OpenAICompatProvider:
    def __init__(
        self,
        name: str,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: int = 60,
    ) -> None:
        self.name = name
        self.model = model
        self._base = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        # Persistent connection pool: reuse TCP connections across requests
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                    keepalive_expiry=30.0,
                ),
                http2=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the persistent connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _body(self, request: LLMRequest, stream: bool) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        model = request.model_override or self.model
        return {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
            "stop": request.stop or None,
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        import asyncio
        max_retries = 3
        last_exc = None
        client = self._get_client()
        for attempt in range(max_retries):
            try:
                r = await client.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=self._body(request, stream=False),
                )
                if r.status_code >= 400:
                    error_data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                    error_msg = error_data.get("error", {}).get("message", r.text)
                    if "Model unloaded" in error_msg or "Operation canceled" in error_msg:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 * (attempt + 1))
                            continue
                    raise LLMError(f"openai-compat {r.status_code}: {error_msg}")
                data = r.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return LLMResponse(
                    content=choice,
                    provider=self.name,
                    model=self.model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise LLMError(f"connection failed after {max_retries} retries: {exc}") from exc
            except LLMError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise
        raise LLMError(f"all retries failed: {last_exc}") from last_exc

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        client = self._get_client()
        async with client.stream(
            "POST",
            f"{self._base}/chat/completions",
            headers=self._headers(),
            json=self._body(request, stream=True),
        ) as r:
            if r.status_code >= 400:
                raise LLMError(f"openai-compat stream {r.status_code}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content")
                if delta:
                    yield delta

    async def health(self) -> bool:
        try:
            client = self._get_client()
            r = await client.get(f"{self._base}/models", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False
