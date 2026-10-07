"""MCP 客户端测试（mcp/client.py 覆盖补齐）—— 用伪服务器 transport，无子进程/无网络。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from more_core.mcp.client import MCPClient, MCPClientError, MCPClientSession
from more_core.mcp.protocol import ClientCapabilities


class _FakeServer:
    """把 write 进来的请求转成响应塞进 inbox，供 read 取出。"""

    def __init__(self, handlers: dict[str, Any] | None = None, *, reply: Any = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._inbox: list[str] = []
        self._handlers = handlers or {}
        self._reply_override = reply

    async def write(self, message: str) -> None:
        obj = json.loads(message)
        self.sent.append(obj)
        if "id" not in obj:  # notification，无响应
            return
        if self._reply_override is not None:
            self._inbox.append(self._reply_override)
            return
        handler = self._handlers.get(obj.get("method"))
        if handler is None:
            body = {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
        else:
            body = handler(obj["id"], obj.get("params", {}))
        self._inbox.append(json.dumps(body))

    async def read(self) -> str:
        return self._inbox.pop(0)

    @property
    def session(self) -> MCPClientSession:
        return MCPClientSession(self.read, self.write)


def _ok_handlers() -> dict[str, Any]:
    return {
        "initialize": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "fake-mcp", "version": "9.9"},
            },
        },
        "tools/list": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"tools": [{"name": "echo", "description": "d", "inputSchema": {}}]},
        },
        "tools/call": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        },
        "resources/list": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"resources": [{"uri": "file:///a", "name": "a"}]},
        },
        "resources/read": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"contents": [{"uri": p.get("uri")}]},
        },
        "prompts/list": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"prompts": [{"name": "p1", "description": "d"}]},
        },
        "prompts/get": lambda i, p: {
            "jsonrpc": "2.0",
            "id": i,
            "result": {"messages": [], "name": p.get("name")},
        },
        "shutdown": lambda i, p: {"jsonrpc": "2.0", "id": i, "result": {}},
    }


async def _initialized_session() -> tuple[MCPClientSession, _FakeServer]:
    srv = _FakeServer(_ok_handlers())
    sess = srv.session
    await sess.initialize(ClientCapabilities(), {"name": "c", "version": "1"})
    return sess, srv


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_success_and_notification():
    sess, srv = await _initialized_session()
    assert sess._initialized is True
    assert sess._server_info.name == "fake-mcp"
    assert sess._server_info.version == "9.9"
    # 初始化后必须回送 initialized 通知
    assert any(m.get("method") == "initialized" for m in srv.sent)


@pytest.mark.asyncio
async def test_initialize_passes_auth_token():
    srv = _FakeServer(_ok_handlers())
    sess = srv.session
    await sess.initialize(ClientCapabilities(), {"name": "c"}, auth_token="tok")
    init = next(m for m in srv.sent if m.get("method") == "initialize")
    assert init["params"]["_auth"]["token"] == "tok"


@pytest.mark.asyncio
async def test_initialize_error_response_raises():
    srv = _FakeServer(
        reply=json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}})
    )
    with pytest.raises(MCPClientError) as ei:
        await srv.session.initialize(ClientCapabilities(), {"name": "c"})
    assert "Initialize failed" in str(ei.value)


# ---------------------------------------------------------------------------
# 未初始化守卫
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.list_tools(),
        lambda s: s.call_tool("t", {}),
        lambda s: s.list_resources(),
        lambda s: s.read_resource("uri"),
        lambda s: s.list_prompts(),
        lambda s: s.get_prompt("p"),
    ],
)
async def test_methods_require_initialization(call):
    sess = _FakeServer(_ok_handlers()).session
    with pytest.raises(MCPClientError) as ei:
        await call(sess)
    assert "Not initialized" in str(ei.value)


# ---------------------------------------------------------------------------
# 各类调用
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_and_call_tool():
    sess, _ = await _initialized_session()
    tools = await sess.list_tools()
    assert [t.name for t in tools] == ["echo"]

    result = await sess.call_tool("echo", {"x": 1})
    assert result.isError is False
    assert result.content[0]["text"] == "ok"


@pytest.mark.asyncio
async def test_resources_and_prompts():
    sess, _ = await _initialized_session()
    res = await sess.list_resources()
    assert [r.uri for r in res] == ["file:///a"]
    assert (await sess.read_resource("file:///a"))["contents"][0]["uri"] == "file:///a"

    prompts = await sess.list_prompts()
    assert [p.name for p in prompts] == ["p1"]
    assert (await sess.get_prompt("p1"))["name"] == "p1"


@pytest.mark.asyncio
async def test_call_error_response_raises():
    handlers = _ok_handlers()
    handlers["tools/list"] = lambda i, p: {
        "jsonrpc": "2.0",
        "id": i,
        "error": {"code": -1, "message": "boom"},
    }
    srv = _FakeServer(handlers)
    sess = srv.session
    await sess.initialize(ClientCapabilities(), {"name": "c"})
    with pytest.raises(MCPClientError) as ei:
        await sess.list_tools()
    assert "List tools failed" in str(ei.value)


@pytest.mark.asyncio
async def test_shutdown_marks_uninitialized():
    sess, _ = await _initialized_session()
    await sess.shutdown()
    assert sess._initialized is False
    await sess.shutdown()  # 再次调用是 no-op


# ---------------------------------------------------------------------------
# 协议层异常
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_response_raises():
    srv = _FakeServer(reply="")
    sess = srv.session
    with pytest.raises(MCPClientError, match="Empty response"):
        await sess.initialize(ClientCapabilities(), {"name": "c"})


@pytest.mark.asyncio
async def test_unexpected_response_type_raises():
    srv = _FakeServer(reply=json.dumps({"jsonrpc": "2.0", "method": "notify", "params": {}}))
    sess = srv.session
    with pytest.raises(MCPClientError, match="Unexpected response type"):
        await sess.initialize(ClientCapabilities(), {"name": "c"})


# ---------------------------------------------------------------------------
# MCPClient 连接管理
# ---------------------------------------------------------------------------


class _FakeTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.disconnected = False
        self._fail = fail

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_client_connect_registers_session_and_transport():
    srv = _FakeServer(_ok_handlers())
    transport = _FakeTransport()
    client = MCPClient()

    await client.connect("s1", srv.read, srv.write, transport=transport)
    assert client.list_sessions() == ["s1"]
    assert client.get_session("s1") is not None

    await client.disconnect("s1")
    assert client.list_sessions() == []
    assert transport.disconnected is True


@pytest.mark.asyncio
async def test_client_connect_failure_disconnects_transport():
    srv = _FakeServer(
        reply=json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "x"}})
    )
    transport = _FakeTransport()
    client = MCPClient()
    with pytest.raises(MCPClientError):
        await client.connect("bad", srv.read, srv.write, transport=transport)
    assert transport.disconnected is True, "初始化失败必须回收 transport（防子进程泄漏）"
    assert client.list_sessions() == []


@pytest.mark.asyncio
async def test_client_disconnect_unknown_is_noop():
    client = MCPClient()
    await client.disconnect("ghost")  # 不应抛异常
    assert client.list_sessions() == []


@pytest.mark.asyncio
async def test_client_list_all_tools_and_call_from_server():
    srv = _FakeServer(_ok_handlers())
    client = MCPClient()
    await client.connect("s1", srv.read, srv.write)

    all_tools = await client.list_all_tools()
    assert [t.name for t in all_tools["s1"]] == ["echo"]

    result = await client.call_tool_from_server("s1", "echo", {"a": 1})
    assert result.isError is False
