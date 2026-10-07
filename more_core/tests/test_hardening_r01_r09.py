"""R-02/R-03/R-04/R-09 回归测试（2026-10-04 加固批次）。"""

from __future__ import annotations

import json

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from more_core.core.native_executor.planner import TaskTemplateSelector
from more_core.security.principal import (
    ANONYMOUS,
    ENV_KEY_PRINCIPAL,
    get_principal,
    principal_from_api_key_id,
    reset_principal,
    set_principal,
)
from more_core.layers.l0_execution import ExecutionLayer

from types import SimpleNamespace


# ---------------------------------------------------------------------------
# R-04 模板路由：不再把 docs/metrics/statistics/fps 误判为 CS 射击
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("补充 docs 文档", "generic"),
        ("导出 metrics 指标", "generic"),
        ("写 statistics 模块", "generic"),
        ("更新 API specs", "generic"),
        ("优化 fps 到 60", "generic"),
        ("统计日志里 fps 关键字出现次数", "generic"),
        ("用 FastAPI 写用户 CRUD", "generic"),
        ("开发俄罗斯方块 tetris", "tetris"),
    ],
)
def test_template_router_avoids_substring_false_positives(query, expected):
    assert TaskTemplateSelector().key_for(SimpleNamespace(query=query), None) == expected


@pytest.mark.parametrize(
    "query",
    [
        "使用 Rust 开发 CS 风格射击游戏 shooter fps",
        "实现 counter-strike 风格对战",
        "用 Rust 写一个 CS 游戏",
        "做一个第一人称射击 demo",
    ],
)
def test_template_router_still_detects_real_shooter_tasks(query):
    assert TaskTemplateSelector().key_for(SimpleNamespace(query=query), None) == "cs_shooter"


# ---------------------------------------------------------------------------
# R-03 主体：来自凭证而非请求体
# ---------------------------------------------------------------------------


def test_principal_mapping_from_credentials():
    assert principal_from_api_key_id("env:MORE_API_KEY") == ENV_KEY_PRINCIPAL
    assert principal_from_api_key_id("key_abc123") == "apikey:key_abc123"
    assert principal_from_api_key_id(None) == ANONYMOUS


def test_principal_contextvar_roundtrip():
    reset_principal()
    assert get_principal() == ""
    set_principal("apikey:key_x")
    assert get_principal() == "apikey:key_x"
    reset_principal()
    assert get_principal() == ""


def test_http_layer_binds_credential_principal(tmp_path, monkeypatch):
    """鉴权成功后 request.state.principal 必须由凭证派生（不可由请求体伪造）。"""
    from more_core.api.server import _require_api_key
    from more_core.security.api_key_store import APIKeyStore, set_default_store

    monkeypatch.setenv("MORE_API_KEY_PEPPER", "pepper")
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    store = APIKeyStore(tmp_path / "k.db")
    raw, _ = store.register(label="t", scopes=["tasks:execute"])
    set_default_store(store)

    app = FastAPI()

    @app.get("/whoami", dependencies=[Depends(_require_api_key)])
    async def whoami(request: Request):
        return {"principal": request.state.principal}

    r = TestClient(app).get("/whoami", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    assert r.json()["principal"].startswith("apikey:key_")
    set_default_store(None)
    store.close()


# ---------------------------------------------------------------------------
# R-02 MCP：非 initialize 方法必须已鉴权
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_rejects_unauthenticated_tool_call(monkeypatch):
    from more_core.mcp.protocol import ToolCallResult
    from more_core.mcp.server import MCPServer

    monkeypatch.setenv("MORE_MCP_KEY", "supersecret")
    srv = MCPServer()

    async def danger(args):
        return ToolCallResult(content=[{"type": "text", "text": "EXECUTED"}])

    srv.register_tool("shell_exec", "x", {"type": "object"}, danger)

    def msg(method, params):
        return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    out = await srv._handler.handle_message(
        msg("tools/call", {"name": "shell_exec", "arguments": {}})
    )
    assert "Unauthorized" in out and "EXECUTED" not in out

    out = await srv._handler.handle_message(msg("tools/list", {}))
    assert "Unauthorized" in out


@pytest.mark.asyncio
async def test_mcp_allows_after_valid_initialize(monkeypatch):
    from more_core.mcp.protocol import ToolCallResult
    from more_core.mcp.server import MCPServer

    monkeypatch.setenv("MORE_MCP_KEY", "supersecret")
    srv = MCPServer()

    async def danger(args):
        return ToolCallResult(content=[{"type": "text", "text": "EXECUTED"}])

    srv.register_tool("shell_exec", "x", {"type": "object"}, danger)

    def msg(method, params):
        return json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    bad = await srv._handler.handle_message(
        msg("initialize", {"_auth": {"token": "wrong"}, "capabilities": {}})
    )
    assert "Unauthorized" in bad

    ok = await srv._handler.handle_message(
        msg("initialize", {"_auth": {"token": "supersecret"}, "capabilities": {}})
    )
    assert "protocolVersion" in ok

    out = await srv._handler.handle_message(
        msg("tools/call", {"name": "shell_exec", "arguments": {}})
    )
    assert "EXECUTED" in out


@pytest.mark.asyncio
async def test_mcp_dev_mode_without_token_stays_open(monkeypatch):
    """未配置令牌时保持开发模式可用（向后兼容）。"""
    from more_core.mcp.protocol import ToolCallResult
    from more_core.mcp.server import MCPServer

    monkeypatch.delenv("MORE_MCP_KEY", raising=False)
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    srv = MCPServer()

    async def danger(args):
        return ToolCallResult(content=[{"type": "text", "text": "EXECUTED"}])

    srv.register_tool("shell_exec", "x", {"type": "object"}, danger)
    out = await srv._handler.handle_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "shell_exec", "arguments": {}},
            }
        )
    )
    assert "EXECUTED" in out


# ---------------------------------------------------------------------------
# R-09 断言默认策略
# ---------------------------------------------------------------------------


def test_assertions_explicit_list_wins():
    got = ExecutionLayer._resolve_assertions({"assertions": ["assert f(1) == 2"]})
    assert got == ["assert f(1) == 2"]


def test_assertions_auto_generated_from_expected_symbols():
    got = ExecutionLayer._resolve_assertions({"expected_symbols": ["merge_intervals", "Helper"]})
    assert got and len(got) == 2
    # D-2 修复后派生的是**表达式**（拼接器负责加 assert 与提示语），
    # 不能再带 `assert` 前缀，否则会被二次包裹成非法语法。
    assert all(not line.startswith("assert") for line in got)
    assert any("merge_intervals" in line for line in got)


def test_assertions_can_be_disabled_explicitly():
    got = ExecutionLayer._resolve_assertions(
        {"expected_symbols": ["f"], "require_assertions": False}
    )
    assert got is None


def test_assertions_ignores_non_identifier_symbols():
    got = ExecutionLayer._resolve_assertions({"expected_symbols": ["not an id", "ok_name"]})
    assert got and len(got) == 1 and "ok_name" in got[0]
