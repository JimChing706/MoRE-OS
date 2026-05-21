"""MCP Registry - manages tools, resources, and prompts."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from .protocol import ToolCallResult

_log = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for MCP tools."""
    
    def __init__(self) -> None:
        self._tools: dict[str, Callable[[dict[str, Any]], Awaitable[ToolCallResult]]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
    
    def register(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[ToolCallResult]],
    ) -> None:
        """Register a tool."""
        self._tools[name] = handler
        self._metadata[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        _log.debug(f"Registered MCP tool: {name}")
    
    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)
        self._metadata.pop(name, None)
        _log.debug(f"Unregistered MCP tool: {name}")
    
    def get(self, name: str) -> Callable[[dict[str, Any]], Awaitable[ToolCallResult]] | None:
        """Get tool handler."""
        return self._tools.get(name)
    
    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools."""
        return list(self._metadata.values())
    
    def get_tool_metadata(self, name: str) -> dict[str, Any] | None:
        """Get tool metadata."""
        return self._metadata.get(name)


class ResourceRegistry:
    """Registry for MCP resources."""
    
    def __init__(self) -> None:
        self._resources: dict[str, Callable[[], Awaitable[str]]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[Callable[[str], Awaitable[None]]]] = {}
    
    def register(
        self,
        uri: str,
        name: str,
        description: str | None = None,
        mime_type: str | None = None,
        read_handler: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Register a resource."""
        self._resources[uri] = read_handler or (lambda: "")
        self._metadata[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
        }
        _log.debug(f"Registered MCP resource: {uri}")
    
    def unregister(self, uri: str) -> None:
        """Unregister a resource."""
        self._resources.pop(uri, None)
        self._metadata.pop(uri, None)
        self._subscribers.pop(uri, None)
        _log.debug(f"Unregistered MCP resource: {uri}")
    
    async def read(self, uri: str) -> str:
        """Read a resource."""
        handler = self._resources.get(uri)
        if handler:
            return await handler()
        return ""
    
    def list_resources(self) -> list[dict[str, Any]]:
        """List all registered resources."""
        return list(self._metadata.values())
    
    def subscribe(self, uri: str, callback: Callable[[str], Awaitable[None]]) -> None:
        """Subscribe to resource changes."""
        if uri not in self._subscribers:
            self._subscribers[uri] = []
        self._subscribers[uri].append(callback)
    
    def unsubscribe(self, uri: str, callback: Callable[[str], Awaitable[None]]) -> None:
        """Unsubscribe from resource changes."""
        if uri in self._subscribers:
            self._subscribers[uri].remove(callback)
    
    async def notify_subscribers(self, uri: str, content: str) -> None:
        """Notify subscribers of resource change."""
        if uri in self._subscribers:
            for callback in self._subscribers[uri]:
                try:
                    await callback(content)
                except Exception as e:
                    _log.error(f"Error notifying subscriber for {uri}: {e}")


class PromptRegistry:
    """Registry for MCP prompts."""
    
    def __init__(self) -> None:
        self._prompts: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
    
    def register(
        self,
        name: str,
        description: str,
        arguments_schema: list[dict[str, Any]] | None = None,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        """Register a prompt."""
        self._prompts[name] = handler or (lambda _: {"messages": []})
        self._metadata[name] = {
            "name": name,
            "description": description,
            "arguments": arguments_schema,
        }
        _log.debug(f"Registered MCP prompt: {name}")
    
    def unregister(self, name: str) -> None:
        """Unregister a prompt."""
        self._prompts.pop(name, None)
        self._metadata.pop(name, None)
        _log.debug(f"Unregistered MCP prompt: {name}")
    
    async def get(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Get prompt content."""
        handler = self._prompts.get(name)
        if handler:
            return await handler(arguments)
        return {"messages": []}
    
    def list_prompts(self) -> list[dict[str, Any]]:
        """List all registered prompts."""
        return list(self._metadata.values())


class MCPRegistry:
    """Combined registry for MCP components."""
    
    def __init__(self) -> None:
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self.prompts = PromptRegistry()
    
    def register_tool_from_registry(self, tool_registry: Any, mcp_name: str | None = None) -> None:
        """Register tools from MoRE OS tool registry."""
        try:
            import importlib.util
            if importlib.util.find_spec("more_core.tools.registry") is None:
                raise ImportError("MoRE OS tool registry not found")

            for tool_def in tool_registry.list():
                self.tools.register(
                    name=mcp_name or tool_def.name,
                    description=tool_def.description,
                    input_schema=tool_def.parameters_schema,
                    handler=self._create_tool_handler(tool_def.handler),
                )
        except ImportError:
            _log.warning("MoRE OS tool registry not available")
    
    def _create_tool_handler(self, handler: Callable[..., Awaitable[Any]]) -> Callable[[dict[str, Any]], Awaitable[ToolCallResult]]:
        """Create MCP tool handler from MoRE OS tool handler."""
        async def wrapper(arguments: dict[str, Any]) -> ToolCallResult:
            try:
                result = await handler(arguments)
                return ToolCallResult(
                    content=[{"type": "text", "text": str(result)}],
                    isError=not result.success if hasattr(result, "success") else False,
                )
            except Exception as e:
                return ToolCallResult(
                    content=[{"type": "text", "text": str(e)}],
                    isError=True,
                )
        return wrapper