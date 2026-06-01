"""Stable plugin contract.

Industry packs (code assistant, data analysis, customer service, …) must
implement :class:`PluginInterface`.  The contract is *frozen* for at least
12 months per platform goal G6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime.orchestrator import MoRECore


@dataclass(slots=True)
class PluginMetadata:
    """Static plugin description (parsed from ``plugin.json``)."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    entry_point: str = "main"
    capabilities: list[str] = field(default_factory=list)
    min_core_version: str = "0.3.0"


@dataclass(slots=True)
class PluginContext:
    """Dependency container handed to plugins at activation time."""

    core: "MoRECore"
    settings: Any
    event_bus: Any
    logger: Any


@runtime_checkable
class PluginInterface(Protocol):
    """Plugin entry class must be named ``Plugin`` in the entry module."""

    metadata: PluginMetadata

    async def activate(self, ctx: PluginContext) -> None: ...

    async def deactivate(self) -> None: ...

    def capabilities(self) -> dict[str, Any]: ...
