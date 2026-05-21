"""MCP HTTP Client - HTTP transport for MCP protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .protocol import (
    JSONRPCProtocol,
    ServerCapabilities,
    Tool,
    Resource,
    Prompt,
    InitializeResult,
)


@dataclass
class MCPHTTPClientConfig:
    """MCP HTTP client configuration."""
    url: str
    headers: dict = field(default_factory=dict)
    timeout: int = 60
    verify_ssl: bool = True


class MCPHTTPClient:
    """MCP client with HTTP transport - for connecting to HTTP-based MCP servers."""
    
    def __init__(self, config: MCPHTTPClientConfig):
        self._config = config
        self._session: httpx.AsyncClient | None = None
        self._protocol = JSONRPCProtocol()
        self._server_capabilities: ServerCapabilities | None = None
        self._server_info: dict = {}
        self._initialized = False
        self._request_id = 0
        self._tools: list[Tool] = []
        self._resources: list[Resource] = []
        self._prompts: list[Prompt] = []
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
    
    async def connect(self) -> None:
        """Connect to MCP server."""
        self._session = httpx.AsyncClient(
            headers=self._config.headers,
            timeout=self._config.timeout,
            verify=self._config.verify_ssl,
        )
    
    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        if self._session:
            await self._session.aclose()
            self._session = None
    
    async def initialize(
        self,
        client_info: dict[str, Any] | None = None,
    ) -> InitializeResult:
        """Initialize connection with MCP server via HTTP."""
        client_info = client_info or {"name": "more-core-mcp-client", "version": "0.3.0"}
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": client_info,
            },
        }
        
        response = await self._send_request(request)
        
        if "error" in response:
            raise RuntimeError(f"MCP initialize failed: {response['error']}")
        
        result = response.get("result", {})
        self._server_info = result.get("serverInfo", {})
        self._server_capabilities = ServerCapabilities(**result.get("capabilities", {}))
        self._initialized = True
        
        await self._initialized_notification()
        
        await self._discover_capabilities()
        
        return InitializeResult(
            serverInfo=self._server_info,
            capabilities=self._server_capabilities,
            protocolVersion=result.get("protocolVersion", "2024-11-05"),
        )
    
    async def _initialized_notification(self) -> None:
        """Send initialized notification."""
        await self._send_notification({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        })
    
    async def _discover_capabilities(self) -> None:
        """Discover server capabilities."""
        self._tools = await self.list_tools()
        self._resources = await self.list_resources()
        self._prompts = await self.list_prompts()
    
    async def list_tools(self) -> list[Tool]:
        """List available tools."""
        if not self._initialized:
            return []
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        
        response = await self._send_request(request)
        tools = response.get("result", {}).get("tools", [])
        return [Tool(**t) for t in tools]
    
    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Call a tool on the MCP server."""
        if not self._initialized:
            raise RuntimeError("Client not initialized")
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        
        response = await self._send_request(request)
        
        if "error" in response:
            raise RuntimeError(f"Tool call failed: {response['error']}")
        
        return response.get("result", {})
    
    async def list_resources(self) -> list[Resource]:
        """List available resources."""
        if not self._initialized:
            return []
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/list",
            "params": {},
        }
        
        response = await self._send_request(request)
        resources = response.get("result", {}).get("resources", [])
        return [Resource(**r) for r in resources]
    
    async def read_resource(self, uri: str) -> dict:
        """Read a resource."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/read",
            "params": {"uri": uri},
        }
        
        response = await self._send_request(request)
        return response.get("result", {})
    
    async def list_prompts(self) -> list[Prompt]:
        """List available prompts."""
        if not self._initialized:
            return []
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "prompts/list",
            "params": {},
        }
        
        response = await self._send_request(request)
        prompts = response.get("result", {}).get("prompts", [])
        return [Prompt(**p) for p in prompts]
    
    async def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        """Get a prompt."""
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "prompts/get",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        
        response = await self._send_request(request)
        return response.get("result", {})
    
    async def shutdown(self) -> None:
        """Shutdown the connection."""
        if not self._initialized:
            return
        
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "shutdown",
            "params": {},
        }
        
        await self._send_request(request)
        self._initialized = False
    
    async def _send_request(self, request: dict) -> dict:
        """Send JSON-RPC request via HTTP."""
        if not self._session:
            raise RuntimeError("Not connected")
        
        r = await self._session.post(self._config.url, json=request)
        r.raise_for_status()
        return r.json()
    
    async def _send_notification(self, notification: dict) -> None:
        """Send JSON-RPC notification via HTTP."""
        if not self._session:
            return
        
        try:
            await self._session.post(self._config.url, json=notification)
        except Exception:
            pass
    
    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id
    
    @property
    def tools(self) -> list[Tool]:
        return self._tools
    
    @property
    def resources(self) -> list[Resource]:
        return self._resources
    
    @property
    def prompts(self) -> list[Prompt]:
        return self._prompts
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def server_info(self) -> dict:
        return self._server_info
    
    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None


async def connect_mcp_http(url: str, **kwargs) -> MCPHTTPClient:
    """Factory function to create and connect MCP HTTP client."""
    config = MCPHTTPClientConfig(url=url, **kwargs)
    client = MCPHTTPClient(config)
    await client.connect()
    await client.initialize()
    return client