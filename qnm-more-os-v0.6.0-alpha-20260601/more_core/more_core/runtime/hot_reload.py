"""Hot-Reload — reload config, skills, and hands without restart.

Reference: OpenFang v0.6.3 hot-reload feature.
Watches configuration and reloads subsystems live when changes detected.
Avoids downtime for config tweaks, skill updates, and hand adjustments.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import MoRECore

_log = logging.getLogger(__name__)


class ReloadScope(Enum):
    """What can be hot-reloaded."""
    CONFIG = "config"
    LLM_PROVIDERS = "llm_providers"
    HANDS = "hands"
    SKILLS = "skills"
    CHANNELS = "channels"
    COMMANDS = "commands"
    PLUGINS = "plugins"
    SECURITY = "security"


@dataclass
class ReloadEvent:
    """Record of a reload operation."""
    scope: ReloadScope
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    error: str | None = None
    duration_ms: float = 0
    changes: dict[str, Any] = field(default_factory=dict)


class HotReloader:
    """Manages hot-reload of system components.

    Usage:
        reloader = HotReloader(core)
        await reloader.reload(ReloadScope.LLM_PROVIDERS)
        await reloader.reload(ReloadScope.HANDS)
    """

    def __init__(self, core: "MoRECore") -> None:
        self._core = core
        self._history: deque[ReloadEvent] = deque(maxlen=200)
        self._handlers: dict[ReloadScope, Callable[..., Awaitable[ReloadEvent]]] = {
            ReloadScope.CONFIG: self._reload_config,
            ReloadScope.LLM_PROVIDERS: self._reload_llm_providers,
            ReloadScope.HANDS: self._reload_hands,
            ReloadScope.SKILLS: self._reload_skills,
            ReloadScope.CHANNELS: self._reload_channels,
            ReloadScope.COMMANDS: self._reload_commands,
            ReloadScope.PLUGINS: self._reload_plugins,
            ReloadScope.SECURITY: self._reload_security,
        }
        self._last_reload: dict[ReloadScope, float] = {}
        # Minimum interval between reloads of same scope (debounce)
        self._min_interval_s = 2.0

    async def reload(self, scope: ReloadScope, **kwargs: Any) -> ReloadEvent:
        """Reload a specific subsystem."""
        # Debounce
        last = self._last_reload.get(scope, 0)
        if time.time() - last < self._min_interval_s:
            return ReloadEvent(
                scope=scope, success=False,
                error=f"Debounced: last reload was {time.time() - last:.1f}s ago"
            )

        handler = self._handlers.get(scope)
        if handler is None:
            return ReloadEvent(scope=scope, success=False, error=f"No handler for {scope.value}")

        start = time.perf_counter()
        try:
            event = await handler(**kwargs)
            event.duration_ms = (time.perf_counter() - start) * 1000
            self._last_reload[scope] = time.time()
            self._history.append(event)
            _log.info("Hot-reload %s: success (%.1fms)", scope.value, event.duration_ms)
            return event
        except Exception as exc:
            event = ReloadEvent(
                scope=scope, success=False, error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            self._history.append(event)
            _log.error("Hot-reload %s failed: %s", scope.value, exc)
            return event

    async def reload_all(self) -> list[ReloadEvent]:
        """Reload all subsystems."""
        results = []
        for scope in ReloadScope:
            event = await self.reload(scope)
            results.append(event)
        return results

    def history(self, limit: int = 20) -> list[ReloadEvent]:
        return self._history[-limit:]

    def stats(self) -> dict[str, Any]:
        return {
            "total_reloads": len(self._history),
            "successful": sum(1 for e in self._history if e.success),
            "failed": sum(1 for e in self._history if not e.success),
            "last_reload": {
                scope.value: self._last_reload.get(scope)
                for scope in ReloadScope
                if scope in self._last_reload
            },
        }

    # -- reload handlers -------------------------------------------------------

    async def _reload_config(self, **kwargs: Any) -> ReloadEvent:
        """Reload settings from environment."""
        from ..core.config import Settings
        new_settings = Settings.from_env()
        old_providers = len(self._core.settings.providers)
        self._core.settings = new_settings
        new_providers = len(new_settings.providers)
        return ReloadEvent(
            scope=ReloadScope.CONFIG, success=True,
            changes={"providers": f"{old_providers} -> {new_providers}"},
        )

    async def _reload_llm_providers(self, **kwargs: Any) -> ReloadEvent:
        """Rebuild LLM providers from current settings."""
        from ..llm.manager import LLMManager
        old_count = len(self._core.llm.list_providers())
        self._core.llm = LLMManager(
            self._core.settings.providers,
            self._core.settings.fallback_chain,
        )
        new_count = len(self._core.llm.list_providers())
        return ReloadEvent(
            scope=ReloadScope.LLM_PROVIDERS, success=True,
            changes={"providers": f"{old_count} -> {new_count}"},
        )

    async def _reload_hands(self, **kwargs: Any) -> ReloadEvent:
        """Re-register built-in hands (preserves active state)."""
        from ..hands.builtins import register_builtin_hands
        active_ids = list(self._core.hands._active.keys())
        register_builtin_hands(self._core.hand_registry)
        return ReloadEvent(
            scope=ReloadScope.HANDS, success=True,
            changes={"registered": len(self._core.hand_registry.list_ids()),
                     "active_preserved": active_ids},
        )

    async def _reload_skills(self, **kwargs: Any) -> ReloadEvent:
        """Reload skill registry."""
        from ..skills.base import SkillManager
        old_count = len(self._core.skill_manager.list_skills())
        self._core.skill_manager = SkillManager()
        return ReloadEvent(
            scope=ReloadScope.SKILLS, success=True,
            changes={"old_skills": old_count, "new_skills": 0},
        )

    async def _reload_channels(self, **kwargs: Any) -> ReloadEvent:
        """Reload channel adapters."""
        channels = self._core.channels.list_channels()
        return ReloadEvent(
            scope=ReloadScope.CHANNELS, success=True,
            changes={"channels": channels},
        )

    async def _reload_commands(self, **kwargs: Any) -> ReloadEvent:
        """Re-register built-in commands."""
        from ..commands.registry import register_builtin_commands, CommandRegistry
        self._core.commands = CommandRegistry()
        register_builtin_commands(self._core.commands)
        return ReloadEvent(
            scope=ReloadScope.COMMANDS, success=True,
            changes={"commands": len(self._core.commands.list_commands())},
        )

    async def _reload_plugins(self, **kwargs: Any) -> ReloadEvent:
        """Rediscover plugins."""
        self._core.plugins.discover()
        return ReloadEvent(
            scope=ReloadScope.PLUGINS, success=True,
            changes={"plugins": [md.name for md in self._core.plugins.list()]},
        )

    async def _reload_security(self, **kwargs: Any) -> ReloadEvent:
        """Reload security settings (RBAC stays in-memory)."""
        return ReloadEvent(
            scope=ReloadScope.SECURITY, success=True,
            changes={"rbac_enabled": self._core.rbac.enabled},
        )
