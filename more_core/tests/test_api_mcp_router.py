"""MCP 路由测试（api/routers/mcp.py 覆盖补齐）—— 用假 client，无 npx/网络。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app
from more_core.mcp.client import MCPClientError
from more_core.mcp.protocol import Tool, ToolCallResult


class _FakeClient:
    def __init__(self) -> None:
        self.sessions: list[str] = []
        self._session_map: dict[str, object] = {}
        self.tool_result = ToolCallResult(content=[{"type": "text", "text": "ok"}], isError=False)
        self.raise_on_call: Exception | None = None
        self.raise_on_list: Exception | None = None
        self.raise_on_disconnect: Exception | None = None
        self.disconnected: list[str] = []

    def list_sessions(self):
        return list(self.sessions)

    def get_session(self, name):
        return self._session_map.get(name)

    async def call_tool_from_server(self, server, tool, args):
        if self.raise_on_call:
            raise self.raise_on_call
        self.called = (server, tool, args)
        return self.tool_result

    async def disconnect(self, name):
        if self.raise_on_disconnect:
            raise self.raise_on_disconnect
        self.disconnected.append(name)

    async def connect(self, **kw):
        self.sessions.append(kw["name"])
        session = MagicMock()
        session.list_tools = AsyncMock(return_value=[Tool(name="read", description="d")])
        self._session_map[kw["name"]] = session
        return session


@pytest.fixture()
def client_and_fake(core):
    fake = _FakeClient()
    core._mcp_client = fake  # mcp_client 是只读 property，需设私有字段
    with TestClient(create_app(core)) as c:
        yield c, fake


def test_list_servers_empty(client_and_fake):
    c, _ = client_and_fake
    body = c.get("/api/v1/mcp/servers").json()
    assert body == {"servers": [], "count": 0}


def test_list_servers_with_sessions(client_and_fake):
    c, fake = client_and_fake
    fake.sessions = ["a", "b"]
    body = c.get("/api/v1/mcp/servers").json()
    assert body["count"] == 2 and body["servers"] == ["a", "b"]


def test_connect_filesystem_already_connected(client_and_fake):
    c, fake = client_and_fake
    fake.sessions = ["filesystem"]
    body = c.post("/api/v1/mcp/connect/filesystem").json()
    assert body["status"] == "already_connected"


def test_connect_filesystem_error_returns_status(client_and_fake, monkeypatch):
    c, _ = client_and_fake
    from more_core.api.routers import mcp as mcp_router

    class _Bad:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            raise RuntimeError("npx missing")

    monkeypatch.setattr(mcp_router, "ProcessTransport", _Bad)
    body = c.post("/api/v1/mcp/connect/filesystem").json()
    assert body["status"] == "error" and "npx missing" in body["error"]


def test_call_tool_success(client_and_fake):
    c, fake = client_and_fake
    body = c.post("/api/v1/mcp/tools/fs/read", json={"path": "/tmp"}).json()
    assert body["status"] == "success"
    assert body["server"] == "fs" and body["tool"] == "read"
    assert fake.called == ("fs", "read", {"path": "/tmp"})


def test_call_tool_error(client_and_fake):
    c, fake = client_and_fake
    fake.raise_on_call = MCPClientError("not initialized")
    body = c.post("/api/v1/mcp/tools/fs/read", json={}).json()
    assert body["status"] == "error" and "not initialized" in body["error"]


def test_list_server_tools_not_connected(client_and_fake):
    c, _ = client_and_fake
    body = c.get("/api/v1/mcp/tools/ghost").json()
    assert body["status"] == "error" and "not connected" in body["error"]


def test_list_server_tools_ok(client_and_fake):
    c, fake = client_and_fake
    session = MagicMock()
    session.list_tools = AsyncMock(return_value=[Tool(name="read", description="read file")])
    fake._session_map["fs"] = session
    body = c.get("/api/v1/mcp/tools/fs").json()
    assert body["count"] == 1
    assert body["tools"][0] == {"name": "read", "description": "read file"}


def test_list_server_tools_exception(client_and_fake):
    c, fake = client_and_fake
    session = MagicMock()
    session.list_tools = AsyncMock(side_effect=RuntimeError("boom"))
    fake._session_map["fs"] = session
    body = c.get("/api/v1/mcp/tools/fs").json()
    assert body["status"] == "error" and "boom" in body["error"]


def test_disconnect_ok_and_error(client_and_fake):
    c, fake = client_and_fake
    c.post("/api/v1/mcp/disconnect/fs")
    assert fake.disconnected == ["fs"]

    fake.raise_on_disconnect = RuntimeError("cannot close")
    body = c.post("/api/v1/mcp/disconnect/fs").json()
    assert body["status"] == "error"
