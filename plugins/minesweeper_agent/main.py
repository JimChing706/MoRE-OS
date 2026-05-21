"""Minesweeper AI agent plugin - provides autonomous play capability

This plugin utilizes MoRE OS LLM Manager to call local models,
combines rule reasoning and probability reasoning for autonomous minesweeper decision-making.
"""

from __future__ import annotations

import asyncio
from typing import Any

from more_core.plugins.sdk import PluginBase, PluginContext
from .agent import MinesweeperAgent


class Plugin(PluginBase):
    NAME = "minesweeper_agent"
    VERSION = "0.1.0"
    DESCRIPTION = "Minesweeper AI agent - rule-based reasoning + LLM enhanced"
    AUTHOR = "QNMing"
    CAPABILITIES = ("ai_decision", "auto_play", "rule_engine", "llm_enhanced")
    DEPENDENCIES = ("minesweeper_game",)

    def __init__(self):
        super().__init__()
        self._ctx: PluginContext | None = None
        self._agent: MinesweeperAgent | None = None

    async def activate(self, ctx: PluginContext) -> None:
        """Activate AI agent plugin"""
        await super().activate(ctx)
        self._ctx = ctx
        self.logger = ctx.logger  # Inject logger

        # 1. Initialize AI agent
        use_llm = ctx.settings.enable_llm if hasattr(ctx.settings, "enable_llm") else True
        llm_model = ctx.settings.ollama_model if hasattr(ctx.settings, "ollama_model") else "llama3.2:3b"

        self._agent = MinesweeperAgent(use_llm=use_llm, llm_model=llm_model)

        # 2. Register decision tools
        from .tools import register_tools
        register_tools(ctx.core.tools)

        # 3. Subscribe to game events
        ctx.event_bus.subscribe("task.started", self._on_task_started)
        ctx.event_bus.subscribe("task.completed", self._on_task_completed)

        self.logger.info(f"Minesweeper Agent activated (LLM: {'enabled' if use_llm else 'disabled'})")

    async def deactivate(self) -> None:
        """Deactivate plugin"""
        if self._ctx and self._ctx.event_bus:
            self._ctx.event_bus.unsubscribe("task.started", self._on_task_started)
            self._ctx.event_bus.unsubscribe("task.completed", self._on_task_completed)

        self._agent = None
        await super().deactivate()
        self.logger.info("Minesweeper Agent deactivated")

    def capabilities(self) -> dict[str, Any]:
        base = super().capabilities()
        base["strategies"] = ["rule_based", "probability", "llm_enhanced"]
        base["default_model"] = "llama3.2:3b"
        return base

    # —— Event Handlers ——

    async def _on_task_started(self, event_data: dict[str, Any]) -> None:
        """Task started event - record game start"""
        if event_data.get("source") == "minesweeper":
            self.logger.info(f"Game task started: {event_data.get('task_id')}")

    async def _on_task_completed(self, event_data: dict[str, Any]) -> None:
        """Task completed event - collect metrics"""
        status = event_data.get("status")
        if status in ("won", "lost"):
            # Record to audit log
            self._ctx.audit.log(
                actor="minesweeper_agent",
                action="game_complete",
                entity="minesweeper_match",
                details={"result": status, "task_id": event_data.get("task_id")},
            )