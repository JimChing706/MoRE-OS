"""Unified Slash Command Registry — single source of truth.

Reference: OpenFang v0.6.0 unified slash command registry.
All commands live in one registry with categories, aliases,
and per-surface filtering (CLI / Channel / Web).
"""

from .registry import Command, CommandRegistry, CommandSurface

__all__ = ["Command", "CommandRegistry", "CommandSurface"]
