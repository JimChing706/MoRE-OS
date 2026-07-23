"""MCP (Model Context Protocol) API router.

Exposes MCP client operations as REST endpoints:
- List connected MCP servers and their tools
- Call MCP tools from connected servers
- Manage MCP server connections
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...version import __version__
from ...runtime.orchestrator import MoRECore
from ...mcp.client import MCPClient, MCPClientError
from ...mcp.protocol import ClientCapabilities
from ...mcp.transport import ProcessTransport


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["MCP"])

    @router.get("/mcp/servers")
    async def list_servers() -> dict[str, Any]:
        """List connected MCP servers."""
        client: MCPClient = core.mcp_client
        sessions = client.list_sessions()
        return {"servers": sessions, "count": len(sessions)}

    @router.post("/mcp/connect/filesystem", dependencies=[Depends(require_api_key)])
    async def connect_filesystem(path: str = "/") -> dict[str, Any]:
        """Connect to the MCP filesystem server (via npx)."""
        client: MCPClient = core.mcp_client
        if "filesystem" in client.list_sessions():
            return {"status": "already_connected", "server": "filesystem"}

        try:
            transport = ProcessTransport(
                command=["npx", "-y", "@modelcontextprotocol/server-filesystem", path],
            )
            await transport.connect()

            async def _read() -> str:
                return await transport.receive()

            async def _write(msg: str) -> None:
                await transport.send(msg)

            session = await client.connect(
                name="filesystem",
                read_callback=_read,
                write_callback=_write,
                client_capabilities=ClientCapabilities(),
                client_info={"name": "QNMing MoRE OS", "version": __version__},
            )
            tools = await session.list_tools()
            return {
                "status": "connected",
                "server": "filesystem",
                "tools": [t.name for t in tools],
                "tool_count": len(tools),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @router.post("/mcp/tools/{server_name}/{tool_name}", dependencies=[Depends(require_api_key)])
    async def call_tool(
        server_name: str, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call a tool on a connected MCP server."""
        client: MCPClient = core.mcp_client
        try:
            result = await client.call_tool_from_server(server_name, tool_name, arguments or {})
            return {
                "status": "success",
                "server": server_name,
                "tool": tool_name,
                "result": result.content if hasattr(result, "content") else str(result),
            }
        except MCPClientError as e:
            return {"status": "error", "error": str(e)}

    @router.get("/mcp/tools/{server_name}")
    async def list_server_tools(server_name: str) -> dict[str, Any]:
        """List tools from a connected MCP server."""
        client: MCPClient = core.mcp_client
        session = client.get_session(server_name)
        if not session:
            return {"status": "error", "error": f"Server '{server_name}' not connected"}
        try:
            tools = await session.list_tools()
            return {
                "server": server_name,
                "tools": [{"name": t.name, "description": t.description} for t in tools],
                "count": len(tools),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @router.post("/mcp/disconnect/{server_name}", dependencies=[Depends(require_api_key)])
    async def disconnect_server(server_name: str) -> dict[str, Any]:
        """Disconnect from an MCP server."""
        client: MCPClient = core.mcp_client
        client.disconnect(server_name)
        return {"status": "disconnected", "server": server_name}

    return router
