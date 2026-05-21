"""MCP Protocol definitions - JSON-RPC 2.0 based."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


class ErrorCode(Enum):
    """JSON-RPC 2.0 error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class MCPMethod(Enum):
    """MCP protocol methods."""
    # Initialization
    INITIALIZE = "initialize"
    INITIALIZED = "initialized"
    
    # Tools
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    
    # Resources
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    RESOURCES_SUBSCRIBE = "resources/subscribe"
    RESOURCES_UNSUBSCRIBE = "resources/unsubscribe"
    
    # Prompts
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"
    
    # Sampling
    SAMPLING_CREATE_MESSAGE = "sampling/createMessage"
    
    # Roots
    ROOTS_LIST = "roots/list"
    ROOTS_CANCEL = "roots/cancel"
    
    # Logging
    LOGGING_SET_LEVEL = "logging/setLevel"
    
    # Lifecycle
    SHUTDOWN = "shutdown"
    EXIT = "exit"


@dataclass
class JSONRPCError:
    """JSON-RPC 2.0 error object."""
    code: int
    message: str
    data: Any = None


@dataclass
class MCPMessage:
    """Base MCP message wrapper."""
    jsonrpc: str = "2.0"
    id: int | str | None = None


@dataclass
class MCPRequest(MCPMessage):
    """MCP request message."""
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResponse(MCPMessage):
    """MCP response message."""
    result: Any = None
    error: JSONRPCError | None = None


@dataclass
class MCPNotification(MCPMessage):
    """MCP notification (no response expected)."""
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    """MCP Tool definition."""
    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resource:
    """MCP Resource definition."""
    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None


@dataclass
class Prompt:
    """MCP Prompt definition."""
    name: str
    description: str
    arguments: list[dict[str, Any]] | None = None


@dataclass
class ServerCapabilities:
    """MCP server capabilities."""
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None


@dataclass
class ClientCapabilities:
    """MCP client capabilities."""
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None


@dataclass
class InitializeResult:
    """Result of initialize method."""
    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: dict[str, Any]


@dataclass
class ToolCallResult:
    """Result of tool call."""
    content: list[dict[str, Any]]
    isError: bool = False


@dataclass
class ResourceContent:
    """Resource content."""
    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None


class JSONRPCProtocol:
    """JSON-RPC 2.0 protocol handler."""
    
    def __init__(self) -> None:
        self._request_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._notification_handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._request_id = 0
        self._pending_requests: dict[str, asyncio.Future[Any]] = {}
    
    def register_handler(self, method: str, handler: Callable[..., Awaitable[Any]]) -> None:
        """Register a request handler."""
        self._request_handlers[method] = handler
    
    def register_notification_handler(self, method: str, handler: Callable[..., Awaitable[None]]) -> None:
        """Register a notification handler."""
        self._notification_handlers[method] = handler
    
    def create_request(self, method: str, params: dict[str, Any] | None = None) -> MCPRequest:
        """Create a new request."""
        self._request_id += 1
        return MCPRequest(
            id=self._request_id,
            method=method,
            params=params or {}
        )
    
    def create_notification(self, method: str, params: dict[str, Any] | None = None) -> MCPNotification:
        """Create a new notification."""
        return MCPNotification(
            method=method,
            params=params or {}
        )
    
    def parse_message(self, data: str | dict) -> MCPMessage | None:
        """Parse JSON-RPC message."""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None
        
        if not isinstance(data, dict):
            return None
        
        if "method" not in data:
            if "result" in data or "error" in data:
                return self._parse_response(data)
            return None
        
        if "id" in data and data["id"] is not None:
            return MCPRequest(
                id=data.get("id"),
                method=data["method"],
                params=data.get("params", {}),
                jsonrpc=data.get("jsonrpc", "2.0")
            )
        else:
            return MCPNotification(
                method=data["method"],
                params=data.get("params", {}),
                jsonrpc=data.get("jsonrpc", "2.0")
            )
    
    def _parse_response(self, data: dict) -> MCPResponse:
        """Parse JSON-RPC response."""
        if "error" in data and data["error"]:
            error_data = data["error"]
            error = JSONRPCError(
                code=error_data.get("code", -32603),
                message=error_data.get("message", "Internal error"),
                data=error_data.get("data")
            )
            return MCPResponse(
                id=data.get("id"),
                error=error,
                jsonrpc=data.get("jsonrpc", "2.0")
            )
        return MCPResponse(
            id=data.get("id"),
            result=data.get("result"),
            jsonrpc=data.get("jsonrpc", "2.0")
        )
    
    def serialize_message(self, msg: MCPMessage) -> str:
        """Serialize MCP message to JSON."""
        data = {"jsonrpc": msg.jsonrpc}
        
        if isinstance(msg, MCPRequest):
            data["method"] = msg.method
            data["params"] = msg.params
            if msg.id is not None:
                data["id"] = msg.id
        elif isinstance(msg, MCPResponse):
            if msg.id is not None:
                data["id"] = msg.id
            if msg.error:
                data["error"] = {
                    "code": msg.error.code,
                    "message": msg.error.message,
                    "data": msg.error.data
                }
            else:
                data["result"] = msg.result
        elif isinstance(msg, MCPNotification):
            data["method"] = msg.method
            data["params"] = msg.params
        
        return json.dumps(data)
    
    async def handle_message(self, msg: MCPMessage) -> MCPResponse | None:
        """Handle incoming message."""
        if isinstance(msg, MCPNotification):
            if msg.method in self._notification_handlers:
                await self._notification_handlers[msg.method](msg.params)
            return None
        
        if isinstance(msg, MCPRequest):
            if msg.method in self._request_handlers:
                try:
                    result = await self._request_handlers[msg.method](msg.params)
                    return MCPResponse(id=msg.id, result=result)
                except Exception as e:
                    return MCPResponse(
                        id=msg.id,
                        error=JSONRPCError(
                            code=ErrorCode.INTERNAL_ERROR.value,
                            message=str(e)
                        )
                    )
            else:
                return MCPResponse(
                    id=msg.id,
                    error=JSONRPCError(
                        code=ErrorCode.METHOD_NOT_FOUND.value,
                        message=f"Method not found: {msg.method}"
                    )
                )
        
        return None