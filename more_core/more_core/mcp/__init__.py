"""MCP (Model Context Protocol) implementation for QNMing MoRE OS.

MCP is a JSON-RPC 2.0 based protocol for communication between AI systems
and external tools/services. This module provides both client and server implementations.

Reference: https://modelcontextprotocol.io/
"""

from .client import MCPClient, MCPClientSession
from .protocol import (
    ClientCapabilities,
    ErrorCode,
    JSONRPCError,
    MCPMessage,
    MCPMethod,
    MCPNotification,
    MCPRequest,
    MCPResponse,
    Prompt,
    Resource,
    ServerCapabilities,
    Tool,
)
from .server import MCPRequestHandler, MCPServer
from .transport import HTTPTransport, ProcessTransport, SSESTransport, StdioTransport

__all__ = [
    "ClientCapabilities",
    "ErrorCode",
    "HTTPTransport",
    "JSONRPCError",
    "MCPClient",
    "MCPClientSession",
    "MCPMessage",
    "MCPMethod",
    "MCPNotification",
    "MCPRequest",
    "MCPRequestHandler",
    "MCPResponse",
    "MCPServer",
    "ProcessTransport",
    "Prompt",
    "Resource",
    "SSESTransport",
    "ServerCapabilities",
    "StdioTransport",
    "Tool",
]
