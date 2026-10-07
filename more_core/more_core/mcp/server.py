"""MCP Server implementation."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .protocol import (
    ClientCapabilities,
    ErrorCode,
    JSONRPCError,
    JSONRPCProtocol,
    MCPRequest,
    MCPResponse,
    ServerCapabilities,
    ToolCallResult,
)

_log = logging.getLogger(__name__)


class MCPServerError(Exception):
    """MCP Server error."""


@dataclass
class ToolHandler:
    """Tool handler definition."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[ToolCallResult]]


@dataclass
class ResourceHandler:
    """Resource handler definition."""

    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = None
    read_handler: Callable[[], Awaitable[str]] | None = None


@dataclass
class PromptHandler:
    """Prompt handler definition."""

    name: str
    description: str
    arguments_schema: list[dict[str, Any]] | None = None
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None


class MCPRequestHandler:
    """Handles MCP requests - registers tools, resources, prompts."""

    def __init__(
        self,
        server_name: str = "QNMing MoRE OS",
        server_version: str = "0.3.0",
    ) -> None:
        self._server_name = server_name
        self._server_version = server_version
        self._protocol = JSONRPCProtocol()
        self._client_capabilities: ClientCapabilities | None = None
        self._initialized = False
        # 会话级鉴权状态：initialize 校验通过后置位；其余方法一律要求已鉴权。
        self._authenticated = False

        self._tools: dict[str, ToolHandler] = {}
        self._resources: dict[str, ResourceHandler] = {}
        self._prompts: dict[str, PromptHandler] = {}

        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Setup protocol handlers."""
        self._protocol.register_handler("initialize", self._handle_initialize)
        self._protocol.register_handler("initialized", self._handle_initialized)
        self._protocol.register_handler("tools/list", self._handle_tools_list)
        self._protocol.register_handler("tools/call", self._handle_tools_call)
        self._protocol.register_handler("resources/list", self._handle_resources_list)
        self._protocol.register_handler("resources/read", self._handle_resources_read)
        self._protocol.register_handler("prompts/list", self._handle_prompts_list)
        self._protocol.register_handler("prompts/get", self._handle_prompts_get)
        self._protocol.register_handler("shutdown", self._handle_shutdown)

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[ToolCallResult]],
    ) -> None:
        """Register a tool."""
        self._tools[name] = ToolHandler(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str | None = None,
        mime_type: str | None = None,
        read_handler: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Register a resource."""
        self._resources[uri] = ResourceHandler(
            uri=uri,
            name=name,
            description=description,
            mime_type=mime_type,
            read_handler=read_handler,
        )

    def register_prompt(
        self,
        name: str,
        description: str,
        arguments_schema: list[dict[str, Any]] | None = None,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        """Register a prompt."""
        self._prompts[name] = PromptHandler(
            name=name,
            description=description,
            arguments_schema=arguments_schema,
            handler=handler,
        )

    def get_capabilities(self) -> ServerCapabilities:
        """Get server capabilities."""
        return ServerCapabilities(
            tools={"listChanged": True} if self._tools else None,
            resources={"subscribe": True, "listChanged": True} if self._resources else None,
            prompts={"listChanged": True} if self._prompts else None,
        )

    @staticmethod
    def _expected_token() -> str:
        """MCP 期望令牌：MORE_MCP_KEY 优先，回退 MORE_API_KEY。空 = 开发模式。"""
        return (os.getenv("MORE_MCP_KEY") or os.getenv("MORE_API_KEY") or "").strip()

    @staticmethod
    def _token_from_params(params: Any) -> str:
        if not isinstance(params, dict):
            return ""
        auth = params.get("_auth")
        if isinstance(auth, dict):
            return str(auth.get("token") or "").strip()
        return str(params.get("token") or "").strip()

    def _is_authorized(self, msg: Any) -> bool:
        """initialize 之外的所有方法都必须在已鉴权会话中执行。

        历史缺陷：只在 initialize 校验令牌，`tools/call` 可被无令牌直接调用，
        等价于把 shell_exec/python_exec 暴露给任何能连上 MCP 通道的进程
        （见 RESIDUAL_RISKS R-02）。
        """
        expected = self._expected_token()
        if not expected:
            return True  # 开发模式：未配置令牌
        if self._authenticated:
            return True
        supplied = self._token_from_params(getattr(msg, "params", None))
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    async def handle_message(self, message: str) -> str | None:
        """Handle incoming message and return response."""
        msg = self._protocol.parse_message(message)
        if not msg:
            return None

        # 鉴权守卫：仅 initialize 可免令牌；其余方法必须是已鉴权会话。
        if isinstance(msg, MCPRequest) and msg.method != "initialize":  # noqa: SIM102 - 保留嵌套以承载逐条件注释
            if not self._is_authorized(msg):
                _log.warning("MCP rejected unauthenticated method=%s", msg.method)
                unauthorized = MCPResponse(
                    id=msg.id,
                    error=JSONRPCError(
                        code=ErrorCode.INVALID_REQUEST.value,
                        message="Unauthorized: initialize with a valid MCP token first",
                    ),
                )
                return self._protocol.serialize_message(unauthorized)

        response = await self._protocol.handle_message(msg)
        if response:
            return self._protocol.serialize_message(response)
        return None

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle initialize request — with optional Bearer token auth."""
        expected = os.getenv("MORE_MCP_KEY", os.getenv("MORE_API_KEY", ""))
        if expected:
            client_token = params.get("_auth", {}).get("token", "")
            if client_token != expected:
                _log.warning("MCP initialize rejected: invalid token")
                raise MCPServerError("Unauthorized: invalid MCP token")
        self._authenticated = True
        self._client_capabilities = ClientCapabilities(**params.get("capabilities", {}))

        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": self.get_capabilities().__dict__,
            "serverInfo": {
                "name": self._server_name,
                "version": self._server_version,
            },
        }

        self._initialized = True
        _log.info("MCP Server initialized by client")
        return result

    async def _handle_initialized(self, params: dict[str, Any]) -> None:
        """Handle initialized notification."""
        _log.debug("Client sent initialized notification")

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request."""
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self._tools.values()
        ]
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self._tools:
            raise MCPServerError(f"Unknown tool: {name}")

        tool = self._tools[name]
        result = await tool.handler(arguments)

        return {
            "content": result.content,
            "isError": result.isError,
        }

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/list request."""
        resources = [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mime_type,
            }
            for r in self._resources.values()
        ]
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")

        if uri not in self._resources:
            raise MCPServerError(f"Unknown resource: {uri}")

        resource = self._resources[uri]

        if resource.read_handler:
            content = await resource.read_handler()
        else:
            content = ""

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": content,
                }
            ]
        }

    async def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle prompts/list request."""
        prompts = [
            {
                "name": p.name,
                "description": p.description,
                "arguments": p.arguments_schema,
            }
            for p in self._prompts.values()
        ]
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle prompts/get request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self._prompts:
            raise MCPServerError(f"Unknown prompt: {name}")

        prompt = self._prompts[name]

        if prompt.handler:
            result = await prompt.handler(arguments)
        else:
            result = {"messages": []}

        return result

    async def _handle_shutdown(self, params: dict[str, Any]) -> None:
        """Handle shutdown request."""
        self._initialized = False
        _log.info("MCP Server shutdown")


class MCPServer:
    """MCP Server - exposes MoRE OS tools via MCP protocol."""

    def __init__(
        self,
        server_name: str = "QNMing MoRE OS",
        server_version: str = "0.3.0",
    ) -> None:
        self._server_name = server_name
        self._server_version = server_version
        self._handler = MCPRequestHandler(server_name, server_version)
        self._running = False

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[ToolCallResult]],
    ) -> None:
        """Register a tool to expose via MCP."""
        self._handler.register_tool(name, description, input_schema, handler)

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str | None = None,
        mime_type: str | None = None,
        read_handler: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Register a resource to expose via MCP."""
        self._handler.register_resource(uri, name, description, mime_type, read_handler)

    def register_prompt(
        self,
        name: str,
        description: str,
        arguments_schema: list[dict[str, Any]] | None = None,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        """Register a prompt to expose via MCP."""
        self._handler.register_prompt(name, description, arguments_schema, handler)

    async def handle_stdio(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle stdio-based MCP connection."""
        _log.info("MCP stdio connection started")

        buffer = ""

        try:
            while self._running:
                line = await reader.readline()
                if not line:
                    break

                buffer += line.decode("utf-8")

                if buffer.strip():
                    response = await self._handler.handle_message(buffer)
                    if response:
                        writer.write((response + "\n").encode("utf-8"))
                        await writer.drain()
                    buffer = ""

        except Exception as e:  # noqa: BLE001
            _log.error(f"MCP stdio error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            _log.info("MCP stdio connection closed")

    async def run_stdio(self) -> None:
        """Run MCP server on stdio."""
        import sys

        self._running = True

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        from .transport import _StdoutProtocol

        writer_protocol = _StdoutProtocol()
        writer_transport, _ = await loop.create_connection(  # type: ignore[call-overload]
            lambda: writer_protocol,
            None,
            None,
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

        await self.handle_stdio(reader, writer)

    async def run_tcp(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Run MCP server on TCP."""
        self._running = True
        server = await asyncio.start_server(
            self.handle_stdio,
            host,
            port,
        )

        _log.info(f"MCP server listening on {host}:{port}")

        async with server:
            await server.serve_forever()

    def get_capabilities(self) -> ServerCapabilities:
        """Get server capabilities."""
        return self._handler.get_capabilities()

    async def shutdown(self) -> None:
        """Shutdown the server."""
        self._running = False
