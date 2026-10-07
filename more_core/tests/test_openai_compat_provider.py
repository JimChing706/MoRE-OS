"""OpenAI 兼容 provider 测试（MockTransport，全程无网络、无重试等待）。"""

from __future__ import annotations

import httpx
import pytest

from more_core.core.errors import LLMError
from more_core.llm.provider import LLMRequest
from more_core.llm.providers import openai_compat as oc
from more_core.llm.providers.openai_compat import (
    OpenAICompatProvider,
    _backoff_delay,
    _is_retryable,
)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """去掉退避等待，让重试类用例瞬时完成。"""
    monkeypatch.setattr(oc, "_backoff_delay", lambda *a, **k: 0.0)


def _provider(handler, **kw) -> OpenAICompatProvider:
    p = OpenAICompatProvider(
        "openai",
        "http://api.test/v1",
        "gpt-x",
        "sk-test",
        timeout=5,
        max_retries=kw.pop("max_retries", 3),
        **kw,
    )
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)
    return p


_OK = {
    "choices": [{"message": {"content": "hi"}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
}


# ---------------------------------------------------------------------------
# 重试判定 / 退避（纯函数）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code,expected", [(429, True), (500, True), (503, True), (504, True)])
def test_retryable_statuses(code, expected):
    assert _is_retryable(code, "") is expected


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_non_retryable_statuses(code):
    assert _is_retryable(code, "") is False


@pytest.mark.parametrize(
    "msg",
    ["model is loading", "rate limit exceeded", "connection reset by peer", "SERVER OVERLOADED"],
)
def test_retryable_message_patterns_case_insensitive(msg):
    assert _is_retryable(418, msg) is True


def test_unknown_error_not_retryable():
    assert _is_retryable(418, "teapot") is False


def test_backoff_grows_and_is_capped():
    assert _backoff_delay(0) <= 1.25
    assert 1.5 <= _backoff_delay(1) <= 2.5
    assert _backoff_delay(20) == 30.0  # 封顶
    assert _backoff_delay(0, base=0.0) == 0.0


# ---------------------------------------------------------------------------
# 请求构造
# ---------------------------------------------------------------------------


def test_headers_and_body_construction():
    p = _provider(lambda r: httpx.Response(200, json=_OK))
    assert p._headers()["Authorization"] == "Bearer sk-test"
    assert p._headers()["Content-Type"] == "application/json"

    body = p._body(
        LLMRequest(prompt="u", system="s", max_tokens=9, stop=["END"], model_override="m2"),
        stream=True,
    )
    assert body["model"] == "m2"
    assert body["stream"] is True and body["max_tokens"] == 9
    assert body["stop"] == ["END"]
    assert body["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success():
    resp = await _provider(lambda r: httpx.Response(200, json=_OK)).generate(
        LLMRequest(prompt="hi")
    )
    assert resp.content == "hi"
    assert resp.prompt_tokens == 3 and resp.completion_tokens == 4
    assert resp.provider == "openai"


@pytest.mark.asyncio
async def test_generate_non_retryable_raises_immediately():
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="hi"))
    assert "HTTP 401" in str(ei.value)
    assert calls["n"] == 1, "不可重试错误不应重试"


@pytest.mark.asyncio
async def test_generate_retries_then_succeeds():
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="model is loading")
        return httpx.Response(200, json=_OK)

    resp = await _provider(handler).generate(LLMRequest(prompt="hi"))
    assert resp.content == "hi"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_generate_exhausts_retries():
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="service unavailable")

    with pytest.raises(LLMError) as ei:
        await _provider(handler, max_retries=3).generate(LLMRequest(prompt="hi"))
    assert "exhausted" in str(ei.value)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_generate_connection_error_after_retries():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError) as ei:
        await _provider(handler, max_retries=2).generate(LLMRequest(prompt="hi"))
    assert "connection failed after 2 retries" in str(ei.value)


@pytest.mark.asyncio
async def test_generate_malformed_payload_raises_llmerror():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(LLMError):
        await _provider(handler).generate(LLMRequest(prompt="hi"))


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_deltas():
    sse = (
        'data: {"choices":[{"delta":{"content":"He"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    chunks = [c async for c in _provider(handler).stream(LLMRequest(prompt="hi"))]
    assert "".join(chunks) == "Hello"


@pytest.mark.asyncio
async def test_stream_http_error_raises():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    with pytest.raises(LLMError):
        [c async for c in _provider(handler).stream(LLMRequest(prompt="hi"))]


# ---------------------------------------------------------------------------
# health / lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_and_lifecycle():
    ok = _provider(lambda r: httpx.Response(200, json={"data": []}))
    assert await ok.health() is True
    await ok.close()
    assert ok._client is None
    await ok.close()  # 幂等

    bad = _provider(lambda r: httpx.Response(500))
    assert await bad.health() is False

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    assert await _provider(boom).health() is False


def test_max_retries_has_floor_of_one():
    p = OpenAICompatProvider("x", "http://x", "m", "k", max_retries=0)
    assert p._max_retries == 1
    assert p._base == "http://x"
