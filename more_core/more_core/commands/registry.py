"""Slash command registry — central source of truth for all commands."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Flag, auto
from typing import Any, Callable, Awaitable

_log = logging.getLogger(__name__)


class CommandSurface(Flag):
    """Where a command is available."""
    CLI = auto()
    WEB = auto()
    CHANNEL = auto()
    ALL = CLI | WEB | CHANNEL


@dataclass
class Command:
    """A registered slash command."""
    name: str
    description: str
    category: str = "general"
    aliases: list[str] = field(default_factory=list)
    surfaces: CommandSurface = CommandSurface.ALL
    handler: Callable[..., Awaitable[Any]] | None = None
    usage: str = ""
    examples: list[str] = field(default_factory=list)
    requires_auth: bool = False


class CommandRegistry:
    """Unified slash command registry.

    Prevents command drift across CLI, web chat, Telegram, Slack, etc.
    Auto-generates help and autocomplete data.
    """

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, command: Command) -> None:
        """Register a command."""
        self._commands[command.name] = command
        for alias in command.aliases:
            self._alias_map[alias] = command.name
        _log.debug("Registered command: /%s", command.name)

    def unregister(self, name: str) -> None:
        cmd = self._commands.pop(name, None)
        if cmd:
            for alias in cmd.aliases:
                self._alias_map.pop(alias, None)

    def get(self, name_or_alias: str) -> Command | None:
        """Resolve a command by name or alias."""
        name = self._alias_map.get(name_or_alias, name_or_alias)
        return self._commands.get(name)

    def list_commands(
        self,
        surface: CommandSurface | None = None,
        category: str | None = None,
    ) -> list[Command]:
        """List commands, optionally filtered by surface and category."""
        result = list(self._commands.values())
        if surface:
            result = [c for c in result if surface in c.surfaces]
        if category:
            result = [c for c in result if c.category == category]
        return sorted(result, key=lambda c: c.name)

    def categories(self) -> list[str]:
        return sorted({c.category for c in self._commands.values()})

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """Execute a command by name."""
        cmd = self.get(name)
        if cmd is None:
            raise KeyError(f"Unknown command: /{name}")
        if cmd.handler is None:
            raise RuntimeError(f"Command /{name} has no handler")
        return await cmd.handler(**kwargs)

    def help_text(self, surface: CommandSurface | None = None) -> str:
        """Generate help text for available commands."""
        lines = ["Available commands:"]
        for cmd in self.list_commands(surface):
            aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  /{cmd.name}{aliases} — {cmd.description}")
        return "\n".join(lines)

    def to_api_dict(self, surface: CommandSurface | None = None) -> list[dict[str, Any]]:
        """Serialize for GET /api/commands endpoint."""
        return [
            {
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "aliases": c.aliases,
                "surfaces": [s.name.lower() for s in CommandSurface if s in c.surfaces and s.name != "ALL"],
                "usage": c.usage,
                "examples": c.examples,
                "requires_auth": c.requires_auth,
            }
            for c in self.list_commands(surface)
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "total_commands": len(self._commands),
            "total_aliases": len(self._alias_map),
            "categories": {cat: len([c for c in self._commands.values() if c.category == cat]) for cat in self.categories()},
        }


def register_builtin_commands(registry: CommandRegistry) -> None:
    """Register platform-level commands."""
    builtins = [
        Command(name="help", description="Show available commands", category="system", aliases=["h", "?"]),
        Command(name="status", description="Show system status", category="system", aliases=["st"]),
        Command(name="health", description="Check system health", category="system"),
        Command(name="hand", description="Manage Hands (list/activate/pause/status)", category="hands",
                aliases=["hands"], usage="/hand <list|activate|pause|status> [hand_id]"),
        Command(name="task", description="Execute a task", category="tasks",
                aliases=["run", "exec"], usage="/task <query>", requires_auth=True),
        Command(name="memory", description="Search or store memory", category="memory",
                usage="/memory <search|store> <query>"),
        Command(name="skill", description="List or run skills", category="skills",
                usage="/skill <list|run> [skill_id]"),
        Command(name="schedule", description="Manage cron schedules", category="cron",
                aliases=["cron"], usage="/schedule <list|add|remove> [job_id]"),
        Command(name="channel", description="Manage channel adapters", category="channels",
                usage="/channel <list|status>"),
        Command(name="llm", description="LLM provider status and control", category="llm",
                usage="/llm <status|switch|reset>"),
        Command(name="zen", description="ZEN rules compliance", category="governance",
                usage="/zen <report|violations>"),
        Command(name="incident", description="Incident management", category="governance",
                aliases=["inc"], usage="/incident <list|resolve> [id]"),
        Command(name="config", description="View/update configuration", category="system",
                requires_auth=True),
        Command(name="stop", description="Stop a running agent or hand", category="system",
                surfaces=CommandSurface.ALL, requires_auth=True),
    ]
    for cmd in builtins:
        registry.register(cmd)
