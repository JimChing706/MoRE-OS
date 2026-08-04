"""Service registry — lightweight, in-process, provider-versioned.

Used by layers, plugins, and runtime to locate each other without hard
imports.  Remote/cluster registries can implement the same API.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Awaitable

from .errors import MoREError
from .types import ServiceMetadata, EngineStatus


class ServiceRegistry:
    """Thread-unsafe single-process registry (async runtime is single-loop)."""

    def __init__(self) -> None:
        self._services: dict[str, ServiceMetadata] = {}
        self._by_provider: dict[str, list[str]] = defaultdict(list)
        self._versions: dict[str, dict[str, str]] = defaultdict(dict)
        self._health_checks: dict[str, Callable[[], Awaitable[bool]]] = {}

    def register(
        self,
        metadata: ServiceMetadata,
        health_check: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        if metadata.name in self._services:
            raise MoREError(f"service already registered: {metadata.name}")
        self._services[metadata.name] = metadata
        self._by_provider[metadata.provider].append(metadata.name)
        self._versions[metadata.provider][metadata.version] = metadata.name
        if health_check is not None:
            self._health_checks[metadata.name] = health_check

    def unregister(self, name: str) -> None:
        md = self._services.pop(name, None)
        if md is None:
            return
        self._by_provider[md.provider].remove(name)
        self._versions[md.provider].pop(md.version, None)
        self._health_checks.pop(name, None)

    def set_status(self, name: str, status: EngineStatus) -> bool:
        """Update a registered service's status. Returns False if unknown."""
        md = self._services.get(name)
        if md is None:
            return False
        md.status = status
        return True

    def get(self, name: str) -> ServiceMetadata | None:
        return self._services.get(name)

    def list_by_provider(self, provider: str) -> list[ServiceMetadata]:
        return [self._services[n] for n in self._by_provider.get(provider, [])]

    def list_all(self) -> list[ServiceMetadata]:
        return list(self._services.values())

    async def health_check(self, name: str) -> bool:
        md = self._services.get(name)
        if md is None:
            return False
        if name in self._health_checks:
            try:
                return await self._health_checks[name]()
            except Exception:
                return False
        return md.status == EngineStatus.RUNNING

    def stats(self) -> dict[str, int]:
        return {
            "total_services": len(self._services),
            "total_providers": len(self._by_provider),
        }
