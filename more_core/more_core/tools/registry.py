"""Typed tool registry — the L0 execution layer dispatches tool calls here.

Every tool is a plain ``async (params: dict) -> ToolResult`` callable with
a JSON-Schema description so the LLM can generate structured invocations.
Plugins register domain tools at activation time; builtins cover code
execution, shell, and web-search stubs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from ..security.rbac import Permission, requires_permission


@dataclass(slots=True, frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON-Schema subset
    handler: Callable[..., Awaitable["ToolResult"]]
    requires_sandbox: bool = False
    tags: tuple[str, ...] = ()
    required_permission: Permission | None = None


@dataclass(slots=True)
class ToolResult:
    tool: str
    success: bool
    output: Any = ""
    error: str = ""
    duration_ms: float = 0.0


class ToolRegistry:
    """Central catalogue of invocable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.required_permission is not None:
            wrapped = requires_permission(tool.required_permission)(tool.handler)
            tool = ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters_schema=tool.parameters_schema,
                handler=wrapped,
                requires_sandbox=tool.requires_sandbox,
                tags=tool.tags,
                required_permission=tool.required_permission,
            )
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-function-calling-compatible schemas."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in self._tools.values()
        ]

    async def invoke(
        self, name: str, params: dict[str, Any], user_id: str = "anonymous"
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool=name, success=False, error=f"unknown tool: {name}")
        # Explicit RBAC check at invoke level (defense in depth)
        if tool.required_permission:
            from ..security.rbac import get_rbac

            rbac = get_rbac()
            if rbac is not None and not rbac.check(user_id, tool.required_permission):
                return ToolResult(
                    tool=name,
                    success=False,
                    error=f"RBAC: user '{user_id}' lacks {tool.required_permission.value} for tool '{name}'",
                )
        params["_user_id"] = user_id  # inject for decorator-level RBAC
        start = time.perf_counter()
        try:
            result = await tool.handler(params)
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as exc:
            return ToolResult(
                tool=name,
                success=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    def stats(self) -> dict[str, Any]:
        return {
            "total": len(self._tools),
            "sandboxed": sum(1 for t in self._tools.values() if t.requires_sandbox),
            "tools": list(self._tools.keys()),
        }
