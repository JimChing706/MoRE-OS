"""Ollama provider 测试（llm/providers/ollama.py 覆盖补齐）——全程 MockTransport，无网络。"""

from __future__ import annotations

import httpx
import pytest

from more_core.core.errors import LLMError
from more_core.llm.provider import LLMRequest
from more_core.llm.providers.ollama import OllamaProvider


def _provider(handler) -> OllamaProvider:
    p = OllamaProvider("ollama", "http://ollama.test", "qwen2.5:7b", timeout=7)
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=7)
    return p


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_parses_response_and_tokens():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/generate"
        return httpx.Response(
            200,
            json={"response": "你好", "prompt_eval_count": 11, "eval_count": 22},
        )

    resp = await _provider(handler).generate(LLMRequest(prompt="hi", max_tokens=16))
    assert resp.content == "你好"
    assert resp.provider == "ollama"
    assert resp.model == "qwen2.5:7b"
    assert resp.prompt_tokens == 11
    assert resp.completion_tokens == 22


@pytest.mark.asyncio
async def test_generate_http_error_raises_llmerror():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="hi"))
    assert "ollama 500" in str(ei.value)


@pytest.mark.asyncio
async def test_generate_connect_error_is_actionable():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="hi"))
    assert "is Ollama running" in str(ei.value)


@pytest.mark.asyncio
async def test_generate_read_timeout_mentions_timeout():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMError) as ei:
        await _provider(handler).generate(LLMRequest(prompt="hi"))
    assert "read timeout after 7s" in str(ei.value)


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_chunks_until_done():
    body = (
        '{"response": "He", "done": false}\n'
        '{"response": "llo", "done": false}\n'
        '{"response": "", "done": true}\n'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    chunks = [c async for c in _provider(handler).stream(LLMRequest(prompt="hi"))]
    assert chunks == ["He", "llo"]


@pytest.mark.asyncio
async def test_stream_skips_malformed_lines():
    body = 'not json\n{"response": "ok", "done": true}\n'

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    chunks = [c async for c in _provider(handler).stream(LLMRequest(prompt="hi"))]
    assert chunks == ["ok"]


@pytest.mark.asyncio
async def test_stream_http_error_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(LLMError):
        [c async for c in _provider(handler).stream(LLMRequest(prompt="hi"))]


# ---------------------------------------------------------------------------
# health / client lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_ok_and_failure():
    def ok(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/tags"
        return httpx.Response(200, json={"models": []})

    assert await _provider(ok).health() is True

    def bad(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert await _provider(bad).health() is False

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    assert await _provider(boom).health() is False


@pytest.mark.asyncio
async def test_get_client_creates_and_reuses():
    p = OllamaProvider("ollama", "http://x/", "m")
    assert p._base == "http://x"  # endpoint 尾斜杠被规范化
    first = p._get_client()
    assert p._get_client() is first
    await p.close()
    assert p._client is None


@pytest.mark.asyncio
async def test_close_is_idempotent():
    p = OllamaProvider("ollama", "http://x", "m")
    await p.close()  # 未创建 client → 不应报错
    p._get_client()
    await p.close()
    await p.close()
    assert p._client is None


@pytest.mark.asyncio
async def test_generate_honours_model_override():
    """回归 D-15：Ollama 此前忽略 request.model_override（直接打自建模型名）。"""
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.url.params) if False else None
        import json as _json

        seen.update(_json.loads(req.content))
        return httpx.Response(200, json={"response": "ok", "eval_count": 1})

    await _provider(handler).generate(LLMRequest(prompt="hi", model_override="other:7b"))
    assert seen["model"] == "other:7b"
