"""Minesweeper AI agent plugin - provides autonomous play capability

This plugin utilizes MoRE OS LLM Manager to call local models,
combines rule reasoning and probability reasoning for autonomous minesweeper decision-making.
"""

from __future__ import annotations

from .agent import MinesweeperAgent