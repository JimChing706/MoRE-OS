"""Minesweeper game plugin - MoRE OS integration entry

This plugin provides:
- Minesweeper game core engine (L0 execution layer)
- Web GUI service (FastAPI + static pages)
- AI auto-play interface
- Collect game metrics for DGM evolution
"""

from __future__ import annotations

from .state_manager import GameSessionManager

# Global singleton instance
session_manager = GameSessionManager()