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


@dataclass(slots=True, frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON-Schema subset
    handler: Callable[..., Awaitable["ToolResult"]]
    requires_sandbox: bool = False
    tags: tuple[str, ...] = ()


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
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self) -> list[ToolDefinition]:
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

    async def invoke(self, name: str, params: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool=name, success=False, error=f"unknown tool: {name}")
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
