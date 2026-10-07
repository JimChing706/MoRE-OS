"""MCP transport 测试（mcp/transport.py 覆盖补齐）。

aiohttp 未安装 → HTTP/SSE 走"优雅降级"路径；ProcessTransport 用真实 `cat` 子进程。
"""

from __future__ import annotations

import json

import pytest

from more_core.core.errors import MCPError
from more_core.mcp.transport import (
    HTTPTransport,
    ProcessTransport,
    SSESTransport,
    StdioTransport,
    _StdoutProtocol,
    create_http_transport,
    create_process_transport,
)

_MSG = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})


# ---------------------------------------------------------------------------
# _StdoutProtocol
# ---------------------------------------------------------------------------


def test_stdout_protocol_tracks_connection():
    proto = _StdoutProtocol()
    assert proto._transport is None
    proto.connection_made(object())  # type: ignore[arg-type]
    assert proto._transport is not None
    assert proto._closed.is_set() is False
    proto.connection_lost(None)
    assert proto._closed.is_set() is True


# ---------------------------------------------------------------------------
# HTTPTransport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_connect_degrades_without_aiohttp():
    t = HTTPTransport("http://mcp.test/")
    assert t._base_url == "http://mcp.test"  # 尾斜杠规范化
    await t.connect()  # aiohttp 未安装 → 警告并降级
    assert t._session is None
    await t.disconnect()  # 无 session 也不应报错


@pytest.mark.asyncio
async def test_http_send_without_session_raises():
    with pytest.raises(MCPError, match="not connected"):
        await HTTPTransport("http://x").send(_MSG)


@pytest.mark.asyncio
async def test_http_receive_is_not_supported():
    with pytest.raises(NotImplementedError):
        await HTTPTransport("http://x").receive()


class _Resp:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return {"ok": True}


class _Session:
    def __init__(self, *, raise_on_json: bool = False):
        self.posts: list[tuple[str, dict]] = []
        self.closed = False

    def post(self, url, json=None):
        self.posts.append((url, json))
        return _Resp()

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_http_send_posts_jsonrpc_body():
    t = HTTPTransport("http://mcp.test")
    t._session = _Session()
    await t.send(_MSG)
    url, body = t._session.posts[0]
    assert url == "http://mcp.test/mcp"
    assert body == {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1}
    await t.disconnect()
    assert t._session.closed is True


@pytest.mark.asyncio
async def test_http_send_ignores_unparseable_message():
    """无法解析的报文不产生 HTTP 请求（通知类报文仍会被转发）。"""
    t = HTTPTransport("http://mcp.test")
    t._session = _Session()
    await t.send("not-json")
    assert t._session.posts == []


@pytest.mark.asyncio
async def test_http_send_forwards_notification():
    t = HTTPTransport("http://mcp.test")
    t._session = _Session()
    await t.send(json.dumps({"jsonrpc": "2.0", "method": "notify", "params": {}}))
    assert t._session.posts and t._session.posts[0][1]["method"] == "notify"


# ---------------------------------------------------------------------------
# SSESTransport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_connect_degrades_and_send_requires_session():
    t = SSESTransport("http://sse.test/")
    await t.connect()
    assert t._session is None
    with pytest.raises(MCPError, match="not connected"):
        await t.send(_MSG)
    await t.disconnect()


@pytest.mark.asyncio
async def test_sse_send_pushes_to_event_queue():
    t = SSESTransport("http://sse.test")
    t._session = _Session()
    await t.send(_MSG)
    assert (await t.events()).get_nowait() == json.dumps({"ok": True})


# ---------------------------------------------------------------------------
# ProcessTransport（真实 cat 子进程）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_transport_roundtrip():
    t = ProcessTransport(["cat"])
    await t.connect()
    try:
        await t.send(_MSG)
        assert await t.receive() == _MSG
    finally:
        await t.disconnect()


@pytest.mark.asyncio
async def test_process_transport_without_process_is_safe():
    t = ProcessTransport(["cat"])
    await t.send(_MSG)  # 未 connect → 静默忽略
    assert await t.receive() == ""  # 无进程 → 返回空串


# ---------------------------------------------------------------------------
# 工厂 + stdio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_process_transport_factory():
    t = await create_process_transport(["cat"])
    try:
        assert isinstance(t, ProcessTransport) and t._process is not None
    finally:
        await t.disconnect()


@pytest.mark.asyncio
async def test_create_http_transport_factory():
    t = await create_http_transport("http://x")
    assert isinstance(t, HTTPTransport)


def test_stdio_transport_constructible():
    t = StdioTransport()
    assert t is not None
