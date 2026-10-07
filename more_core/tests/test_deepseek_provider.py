"""DeepSeek provider 测试（MockTransport，无网络）。"""

from __future__ import annotations

import json

import httpx
import pytest

from more_core.core.errors import LLMError
from more_core.llm.provider import LLMRequest
from more_core.llm.providers.deepseek import DeepSeekProvider


def _provider(handler) -> DeepSeekProvider:
    p = DeepSeekProvider(
        "deepseek", "sk-x", endpoint="http://ds.test", model="deepseek-chat", timeout=7
    )
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=7)
    return p


def _ok_body(content="hi", reasoning=None):
    msg = {"content": content}
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 5, "completion_tokens": 6}}


def test_build_messages():
    p = _provider(lambda r: httpx.Response(200, json=_ok_body()))
    assert p._build_messages(LLMRequest(prompt="u")) == [{"role": "user", "content": "u"}]
    assert p._build_messages(LLMRequest(prompt="u", system="s")) == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


def test_models_mapping_present():
    assert DeepSeekProvider.MODELS["deepseek-chat-v3"] == "deepseek-chat"
    assert "deepseek-reasoner" in DeepSeekProvider.MODELS


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_success_and_reasoning_content():
    p = _provider(lambda r: httpx.Response(200, json=_ok_body("答案", reasoning="思考")))
    resp = await p.generate(LLMRequest(prompt="p"))
    assert resp.content == "答案"
    assert resp.reasoning_content == "思考"
    assert resp.prompt_tokens == 5 and resp.completion_tokens == 6


@pytest.mark.asyncio
async def test_generate_honours_model_override():
    """回归 D-15：此前忽略 request.model_override。"""
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return httpx.Response(200, json=_ok_body())

    await _provider(handler).generate(LLMRequest(prompt="p", model_override="deepseek-reasoner"))
    assert seen["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_generate_enable_thinking_and_default_max_tokens():
    seen: dict = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return httpx.Response(200, json=_ok_body())

    await _provider(handler).generate(LLMRequest(prompt="p", max_tokens=0, enable_thinking=True))
    assert seen["thinking"] == {"type": "enabled"}
    assert seen["max_tokens"] == 4096
    assert seen["stream"] is False


@pytest.mark.asyncio
async def test_generate_connect_error():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="p"))
    assert "connection failed" in str(ei.value)


@pytest.mark.asyncio
async def test_generate_read_timeout():
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="p"))
    assert "read timeout after 7s" in str(ei.value)


@pytest.mark.asyncio
async def test_generate_http_error():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="p"))
    assert "deepseek 400" in str(ei.value)


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_deltas_and_skips_done_and_malformed():
    sse = (
        'data: {"choices":[{"delta":{"content":"He"}}]}\n'
        "data: not-json\n"
        'data: {"choices":[{"delta":{"content":"llo"}}]}\n'
        "data: [DONE]\n"
    )

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse)

    chunks = [c async for c in _provider(handler).stream(LLMRequest(prompt="p"))]
    assert "".join(chunks) == "Hello"


@pytest.mark.asyncio
async def test_stream_honours_model_override():
    seen: dict = {}
    sse = 'data: {"choices":[{"delta":{"content":"x"}}]}\n'

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(json.loads(r.content))
        return httpx.Response(200, text=sse)

    [c async for c in _provider(handler).stream(LLMRequest(prompt="p", model_override="m2"))]
    assert seen["model"] == "m2" and seen["stream"] is True


@pytest.mark.asyncio
async def test_stream_http_error():
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError):
        [c async for c in _provider(handler).stream(LLMRequest(prompt="p"))]


# ---------------------------------------------------------------------------
# health / lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_and_lifecycle():
    def ok(r: httpx.Request) -> httpx.Response:
        assert r.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    p = _provider(ok)
    assert await p.health() is True
    first = p._get_client()
    assert p._get_client() is first
    await p.close()
    assert p._client is None

    assert await _provider(lambda r: httpx.Response(500)).health() is False

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    assert await _provider(boom).health() is False
