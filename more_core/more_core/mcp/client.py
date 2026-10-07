"""MCP Client implementation."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from .protocol import (
    ClientCapabilities,
    InitializeResult,
    JSONRPCProtocol,
    MCPNotification,
    MCPRequest,
    MCPResponse,
    Prompt,
    Resource,
    ServerCapabilities,
    Tool,
    ToolCallResult,
)

_log = logging.getLogger(__name__)


class MCPClientError(Exception):
    """MCP Client error."""


@dataclass
class MCPServerInfo:
    """MCP server information."""

    name: str
    version: str


class MCPClientSession:
    """MCP client session - manages communication with MCP server."""

    def __init__(
        self,
        read_callback: Callable[[], Awaitable[str]],
        write_callback: Callable[[str], Awaitable[None]],
    ) -> None:
        self._read_callback = read_callback
        self._write_callback = write_callback
        self._protocol = JSONRPCProtocol()
        self._server_capabilities: ServerCapabilities | None = None
        self._server_info: MCPServerInfo | None = None
        self._initialized = False
        self._request_id = 0

    async def initialize(
        self,
        client_capabilities: ClientCapabilities,
        client_info: dict[str, Any],
        auth_token: str | None = None,
    ) -> InitializeResult:
        """Initialize connection with MCP server.

        Args:
            client_capabilities: Client capabilities.
            client_info: Client metadata.
            auth_token: Optional token for servers that require auth
                (``MORE_MCP_KEY`` / ``MORE_API_KEY`` on the server side).
        """
        self._request_id += 1
        params: dict[str, Any] = {
            "capabilities": client_capabilities.__dict__,
            "clientInfo": client_info,
        }
        if auth_token:
            params["_auth"] = {"token": auth_token}
        request = MCPRequest(
            id=self._request_id,
            method="initialize",
            params=params,
        )

        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"Initialize failed: {response.error.message}")

        result = response.result
        self._server_capabilities = ServerCapabilities(**result.get("capabilities", {}))
        self._server_info = MCPServerInfo(
            name=result.get("serverInfo", {}).get("name", "unknown"),
            version=result.get("serverInfo", {}).get("version", "unknown"),
        )
        self._initialized = True

        await self._send_notification("initialized", {})

        return InitializeResult(
            protocolVersion=result.get("protocolVersion", "2024-11-05"),
            capabilities=self._server_capabilities,
            serverInfo=result.get("serverInfo", {}),
        )

    async def list_tools(self) -> list[Tool]:
        """List available tools from server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request("tools/list")
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"List tools failed: {response.error.message}")

        tools = response.result.get("tools", [])
        return [Tool(**t) for t in tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolCallResult:
        """Call a tool on the server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"Call tool failed: {response.error.message}")

        return ToolCallResult(**response.result)

    async def list_resources(self) -> list[Resource]:
        """List available resources from server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request("resources/list")
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"List resources failed: {response.error.message}")

        resources = response.result.get("resources", [])
        return [Resource(**r) for r in resources]

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource from server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request("resources/read", {"uri": uri})
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"Read resource failed: {response.error.message}")

        return cast(dict[str, Any], response.result)

    async def list_prompts(self) -> list[Prompt]:
        """List available prompts from server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request("prompts/list")
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"List prompts failed: {response.error.message}")

        prompts = response.result.get("prompts", [])
        return [Prompt(**p) for p in prompts]

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Get a prompt from server."""
        if not self._initialized:
            raise MCPClientError("Not initialized")

        request = self._protocol.create_request(
            "prompts/get", {"name": name, "arguments": arguments or {}}
        )
        response = await self._send_request(request)

        if response.error:
            raise MCPClientError(f"Get prompt failed: {response.error.message}")

        return cast(dict[str, Any], response.result)

    async def shutdown(self) -> None:
        """Shutdown the session."""
        if not self._initialized:
            return

        request = self._protocol.create_request("shutdown")
        await self._send_request(request)
        self._initialized = False

    async def _send_request(self, request: MCPRequest) -> MCPResponse:
        """Send request and wait for response."""
        request.id = self._request_id
        self._request_id += 1

        message = self._protocol.serialize_message(request)
        await self._write_callback(message)

        response_data = await self._read_callback()
        parsed = self._protocol.parse_message(response_data)
        if parsed is None:
            raise MCPClientError("Empty response from server")
        if not isinstance(parsed, MCPResponse):
            raise MCPClientError(f"Unexpected response type: {type(parsed).__name__}")
        return parsed

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send notification (no response expected)."""
        notification = MCPNotification(method=method, params=params)
        message = self._protocol.serialize_message(notification)
        await self._write_callback(message)


class MCPClient:
    """MCP Client - connects to MCP servers."""

    def __init__(self) -> None:
        self._sessions: dict[str, MCPClientSession] = {}
        self._tools_cache: dict[str, list[Tool]] = {}
        self._transports: dict[str, Any] = {}

    async def connect(
        self,
        name: str,
        read_callback: Callable[[], Awaitable[str]],
        write_callback: Callable[[str], Awaitable[None]],
        client_capabilities: ClientCapabilities | None = None,
        client_info: dict[str, Any] | None = None,
        transport: Any | None = None,
        auth_token: str | None = None,
    ) -> MCPClientSession:
        """Connect to an MCP server.

        Args:
            name: Server name (must be unique; existing connection is
                replaced after the old one is shut down).
            read_callback: Read callback used by the session.
            write_callback: Write callback used by the session.
            client_capabilities: Client capabilities for initialize.
            client_info: Client info for initialize.
            transport: Optional transport owned by this client (e.g. a
                subprocess transport); it is disconnected on disconnect()
                and on a failed initialize.
            auth_token: Optional token; defaults to the ``MORE_MCP_KEY`` /
                ``MORE_API_KEY`` env vars, matching the server side.

        Raises:
            MCPClientError: When initialize fails; the transport (if given)
                is disconnected before re-raising so no subprocess leaks.
        """
        if client_capabilities is None:
            client_capabilities = ClientCapabilities()

        if client_info is None:
            client_info = {"name": "QNMing MoRE OS", "version": "0.3.0"}

        if auth_token is None:
            auth_token = os.getenv("MORE_MCP_KEY") or os.getenv("MORE_API_KEY") or None

        session = MCPClientSession(read_callback, write_callback)
        try:
            await session.initialize(client_capabilities, client_info, auth_token=auth_token)
        except Exception:
            if transport is not None:
                await self._disconnect_transport(transport)
            raise

        old_session = self._sessions.get(name)
        if old_session is not None:
            _log.warning("Replacing existing MCP session '%s'", name)
        self._sessions[name] = session
        if transport is not None:
            self._transports[name] = transport
        return session

    async def disconnect(self, name: str) -> None:
        """Disconnect from an MCP server, shutting down its session and
        closing the owned transport (terminates the subprocess)."""
        session = self._sessions.pop(name, None)
        transport = self._transports.pop(name, None)
        if session is not None:
            try:
                await session.shutdown()
            except Exception as exc:  # noqa: BLE001
                _log.warning("MCP shutdown for '%s' failed: %s", name, exc)
        if transport is not None:
            await self._disconnect_transport(transport)

    @staticmethod
    async def _disconnect_transport(transport: Any) -> None:
        try:
            disconnect = getattr(transport, "disconnect", None)
            if disconnect is not None:
                await disconnect()
        except Exception as exc:  # noqa: BLE001
            _log.warning("MCP transport disconnect failed: %s", exc)

    def get_session(self, name: str) -> MCPClientSession | None:
        """Get a session by name."""
        return self._sessions.get(name)

    def list_sessions(self) -> list[str]:
        """List all connected sessions."""
        return list(self._sessions.keys())

    async def call_tool_from_server(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        """Convenience method to call a tool on a specific server."""
        session = self._sessions.get(server_name)
        if not session:
            raise MCPClientError(f"Unknown server: {server_name}")

        return await session.call_tool(tool_name, arguments)

    async def list_all_tools(self) -> dict[str, list[Tool]]:
        """List tools from all connected servers."""
        result = {}
        for name, session in self._sessions.items():
            try:
                tools = await session.list_tools()
                result[name] = tools
                self._tools_cache[name] = tools
            except Exception as e:  # noqa: BLE001
                _log.warning(f"Failed to list tools from {name}: {e}")
        return result
