"""MCP (Model Context Protocol) implementation for QNMing MoRE OS.

MCP is a JSON-RPC 2.0 based protocol for communication between AI systems
and external tools/services. This module provides both client and server implementations.

Reference: https://modelcontextprotocol.io/
"""

from .protocol import (
    MCPMessage,
    MCPRequest,
    MCPResponse,
    MCPNotification,
    JSONRPCError,
    ErrorCode,
    MCPMethod,
    Tool,
    Resource,
    Prompt,
    ServerCapabilities,
    ClientCapabilities,
)
from .client import MCPClient, MCPClientSession
from .server import MCPServer, MCPRequestHandler
from .transport import StdioTransport, SSESTransport, HTTPTransport, ProcessTransport
from .registry import ToolRegistry, ResourceRegistry, PromptRegistry

__all__ = [
    "MCPMessage",
    "MCPRequest", 
    "MCPResponse",
    "MCPNotification",
    "JSONRPCError",
    "ErrorCode",
    "MCPMethod",
    "Tool",
    "Resource", 
    "Prompt",
    "ServerCapabilities",
    "ClientCapabilities",
    "MCPClient",
    "MCPClientSession",
    "MCPServer",
    "MCPRequestHandler",
    "StdioTransport",
    "SSESTransport",
    "HTTPTransport",
    "ProcessTransport",
    "ToolRegistry",
    "ResourceRegistry",
    "PromptRegistry",
]