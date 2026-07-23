"""OpenAI-compatible provider (OpenAI, DeepSeek, Kimi, Zhipu, vLLM, ...).

Enhanced with intelligent retry logic, exponential backoff with jitter,
and provider-identifiable error messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import AsyncIterator

import httpx

from ...core.errors import LLMError
from ..provider import LLMRequest, LLMResponse

_log = logging.getLogger("more_core.llm.openai_compat")

# Status codes that indicate a transient failure worth retrying.
_RETRYABLE_STATUSES: set[int] = {429, 500, 502, 503, 504}

# Error message patterns from LM Studio / vLLM / generic OpenAI-compat servers
# that indicate the model is still loading or temporarily unavailable.
_RETRYABLE_PATTERNS: tuple[str, ...] = (
    "model unloaded",
    "model is loading",
    "model is still loading",
    "operation canceled",
    "model not found",
    "server is starting",
    "server overloaded",
    "service unavailable",
    "too many requests",
    "rate limit",
    "connection reset",
    "connection refused",
    "request timed out",
    "temporarily unavailable",
    "try again",
    "please retry",
)

# Patterns that should NOT be retried (auth, billing, bad requests).
_NON_RETRYABLE_STATUSES: set[int] = {400, 401, 402, 403, 404, 422}


def _is_retryable(status_code: int, error_message: str) -> bool:
    """Determine if an error is retryable based on status code and message."""
    if status_code in _NON_RETRYABLE_STATUSES:
        return False
    if status_code in _RETRYABLE_STATUSES:
        return True
    msg_lower = error_message.lower()
    return any(pat in msg_lower for pat in _RETRYABLE_PATTERNS)


def _backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 30.0) -> float:
    """Exponential backoff with jitter.

    Formula: min(base * 2^attempt + jitter, max_delay)
    Jitter range: ±25% of the exponential component.
    """
    exp = base * (2**attempt)
    jitter = exp * 0.25 * (random.random() * 2 - 1)  # ±25%
    result: float = min(exp + jitter, max_delay)
    return result


class OpenAICompatProvider:
    """Provider for OpenAI-compatible chat/completions APIs.

    Features:
    - Persistent HTTP/1.1 connection pool with keep-alive
    - Intelligent retry with exponential backoff + jitter
    - Distinguishes transient (retryable) vs permanent errors
    - Provider-identifiable error messages for debugging
    """

    def __init__(
        self,
        name: str,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: int = 60,
        max_retries: int = 5,
    ) -> None:
        self.name = name
        self.model = model
        self._base = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        # Use HTTP/1.1 for broader compatibility (LM Studio, vLLM, etc.)
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
                http2=False,  # Better compatibility with local servers
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
        body: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.stop:
            body["stop"] = request.stop
        return body

    def _format_error(self, status_code: int, message: str) -> str:
        """Format an error message with provider and model context."""
        return f"[{self.name}/{self.model}] HTTP {status_code}: {message}"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        last_exc: Exception | None = None
        client = self._get_client()
        effective_model = request.model_override or self.model

        for attempt in range(self._max_retries):
            try:
                r = await client.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=self._body(request, stream=False),
                )

                if r.status_code >= 400:
                    content_type = r.headers.get("content-type", "")
                    if content_type.startswith("application/json"):
                        error_data = r.json()
                        error_msg = error_data.get("error", {}).get("message", r.text)
                    else:
                        error_msg = r.text[:500]

                    formatted = self._format_error(r.status_code, error_msg)

                    if _is_retryable(r.status_code, error_msg):
                        if attempt < self._max_retries - 1:
                            delay = _backoff_delay(attempt)
                            _log.warning(
                                "%s (retryable, attempt %d/%d, waiting %.1fs)",
                                formatted,
                                attempt + 1,
                                self._max_retries,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise LLMError(f"{formatted} (exhausted {self._max_retries} retries)")
                    # Non-retryable error
                    raise LLMError(formatted)

                data = r.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return LLMResponse(
                    content=choice,
                    provider=self.name,
                    model=effective_model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                exc_name = type(exc).__name__
                if attempt < self._max_retries - 1:
                    delay = _backoff_delay(attempt)
                    _log.warning(
                        "[%s/%s] %s (attempt %d/%d, waiting %.1fs): %s",
                        self.name,
                        effective_model,
                        exc_name,
                        attempt + 1,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(
                    f"[{self.name}/{effective_model}] connection failed after "
                    f"{self._max_retries} retries: {exc}"
                ) from exc

            except LLMError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    delay = _backoff_delay(attempt)
                    _log.warning(
                        "[%s/%s] unexpected %s (attempt %d/%d, waiting %.1fs): %s",
                        self.name,
                        effective_model,
                        type(exc).__name__,
                        attempt + 1,
                        self._max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(
                    f"[{self.name}/{effective_model}] unexpected error after "
                    f"{self._max_retries} retries: {exc}"
                ) from exc

        raise LLMError(
            f"[{self.name}/{effective_model}] all {self._max_retries} attempts failed: {last_exc}"
        ) from last_exc

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        client = self._get_client()
        effective_model = request.model_override or self.model

        for attempt in range(self._max_retries):
            try:
                async with client.stream(
                    "POST",
                    f"{self._base}/chat/completions",
                    headers=self._headers(),
                    json=self._body(request, stream=True),
                ) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        try:
                            error_data = json.loads(body)
                            error_msg = error_data.get("error", {}).get("message", str(body))
                        except (json.JSONDecodeError, Exception):
                            error_msg = body.decode("utf-8", errors="replace")[:500]

                        formatted = self._format_error(r.status_code, error_msg)
                        if (
                            _is_retryable(r.status_code, error_msg)
                            and attempt < self._max_retries - 1
                        ):
                            delay = _backoff_delay(attempt)
                            _log.warning(
                                "%s (retryable, attempt %d/%d)",
                                formatted,
                                attempt + 1,
                                self._max_retries,
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise LLMError(formatted)

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
                    return  # Stream completed successfully

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                if attempt < self._max_retries - 1:
                    delay = _backoff_delay(attempt)
                    _log.warning(
                        "[%s/%s] stream %s (attempt %d/%d, waiting %.1fs)",
                        self.name,
                        effective_model,
                        type(exc).__name__,
                        attempt + 1,
                        self._max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise LLMError(
                    f"[{self.name}/{effective_model}] stream connection failed "
                    f"after {self._max_retries} retries: {exc}"
                ) from exc
            except LLMError:
                raise

        raise LLMError(
            f"[{self.name}/{effective_model}] stream all {self._max_retries} attempts failed"
        )

    async def health(self) -> bool:
        try:
            client = self._get_client()
            r = await client.get(f"{self._base}/models", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False
