"""Minesweeper game plugin - MoRE OS integration entry

This plugin provides:
- Minesweeper game core engine (L0 execution layer)
- Web GUI service (FastAPI + static pages)
- AI auto-play interface
- Collect game metrics for DGM evolution
"""

from __future__ import annotations

import asyncio

from more_core.plugins.sdk import PluginBase, PluginContext
from .gui_server import app as minesweeper_app
from .tools import register_tools
# Import global session_manager singleton
from .state_manager import GameSessionManager


# Global singleton instance
session_manager = GameSessionManager()


class Plugin(PluginBase):
    NAME = "minesweeper_game"
    VERSION = "0.1.0"
    DESCRIPTION = "Minesweeper game core engine with Web GUI - supports AI auto-play"
    AUTHOR = "QNMing"
    CAPABILITIES = ("game_engine", "web_gui", "ai_autoplay", "metrics_collection")
    DEPENDENCIES = ()  # No external dependencies (uses FastAPI built-in)

    def __init__(self):
        super().__init__()
        self._ctx: PluginContext | None = None
        self._server_task: asyncio.Task | None = None
        self._host: str = "0.0.0.0"
        self._port: int = 8080

    async def activate(self, ctx: PluginContext) -> None:
        """Activate plugin - register tools and start Web service"""
        await super().activate(ctx)
        self._ctx = ctx
        # Inject logger into instance for convenience
        self.logger = ctx.logger

        # 1. Register minesweeper tools to MoRE OS tool registry
        register_tools(ctx.core.tools)

        # 2. Start session manager
        await session_manager.start()

        # 3. Start FastAPI Web service (in background task)
        self._server_task = asyncio.create_task(
            self._run_server()
        )

        self.logger.info(f"Minesweeper plugin listening on http://{self._host}:{self._port}")

        # 4. Subscribe to event bus
        ctx.event_bus.subscribe("task.started", self._on_task_started)
        ctx.event_bus.subscribe("task.completed", self._on_task_completed)

    async def _run_server(self) -> None:
        """Run FastAPI in separate task"""
        import uvicorn
        config = uvicorn.Config(
            minesweeper_app,
            host=self._host,
            port=self._port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def deactivate(self) -> None:
        """Deactivate plugin - stop Web service and cleanup"""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        await session_manager.stop()

        if self._ctx and self._ctx.event_bus:
            self._ctx.event_bus.unsubscribe("task.started", self._on_task_started)
            self._ctx.event_bus.unsubscribe("task.completed", self._on_task_completed)

        await super().deactivate()
        self.logger.info("Minesweeper plugin deactivated")

    def capabilities(self) -> dict[str, Any]:
        base = super().capabilities()
        base["endpoints"] = {
            "web_gui": f"http://{self._host}:{self._port}",
            "api_docs": f"http://{self._host}:{self._port}/docs",
            "static": f"http://{self._host}:{self._port}/static",
        }
        base["game_config"] = {
            "difficulties": ["beginner", "intermediate", "expert", "custom"],
            "max_concurrent_sessions": 100,
        }
        return base

    # —— Event Handlers ——

    async def _on_task_started(self, event_data: dict[str, Any]) -> None:
        """Task started event - record game start"""
        if event_data.get("source") == "minesweeper":
            self.logger.info(f"Game task started: {event_data.get('task_id')}")

    async def _on_task_completed(self, event_data: dict[str, Any]) -> None:
        """Task completed event - collect metrics and store to evolution archive"""
        status = event_data.get("status")
        if status in ("won", "lost"):
            # Record to audit log
            self._ctx.audit.log(
                actor="minesweeper_plugin",
                action="game_complete",
                entity="minesweeper_match",
                details={
                    "result": status,
                    "task_id": event_data.get("task_id"),
                    "metadata": event_data.get("metadata", {}),
                },
            )

            # Advance evolution: collect game performance data
            try:
                await self._record_evolution_data(event_data)
            except Exception as e:
                self.logger.warning(f"Failed to record evolution data: {e}")

    async def _record_evolution_data(self, event_data: dict[str, Any]) -> None:
        """Store game match data to EvolutionArchive for DGM analysis"""
        core = self._ctx.core
        game_summary = {
            "game_type": "minesweeper",
            "difficulty": event_data.get("metadata", {}).get("difficulty", "unknown"),
            "result": event_data.get("status"),
            "moves": event_data.get("metadata", {}).get("moves", 0),
            "cells_revealed": event_data.get("metadata", {}).get("cells_revealed", 0),
            "timestamp": event_data.get("timestamp", 0),
        }

        score = self._calculate_performance_score(game_summary)

        # Store to EvolutionArchive
        from more_core.evolution.archive import EvolvedAgent
        import time

        agent = EvolvedAgent(
            id=core.evolution_archive.new_id("minesweeper_agent"),
            parent_id=None,
            generation=0,
            branch="rule_based",
            code=self._snapshot_agent_code(),
            performance=score,
            description=f"{game_summary['difficulty']} {game_summary['result']} in {game_summary['moves']} moves",
            created_at=time.time(),
            verified=False,
        )

        core.evolution_archive.add(agent)
        self.logger.info(f"Evolution recorded: score={score:.1f}, agent_id={agent.id}")

    def _snapshot_agent_code(self) -> str:
        """Get current AI agent code snapshot (for evolution tracking)"""
        # Simply return string representation of key reasoning logic
        return "ReasoningEngine(single_rule + subset_constraint) + ProbabilityEngine(basic)"

    def _calculate_performance_score(self, game_summary: dict[str, Any]) -> float:
        """Calculate game performance score (0-100)"""
        if game_summary["result"] == "won":
            base = 100.0
            moves = game_summary.get("moves", 0)
            penalty = min(50.0, moves * 0.2)
            return max(0.0, base - penalty)
        else:
            cells = game_summary.get("cells_revealed", 0)
            total = {
                "beginner": 71,
                "intermediate": 216,
                "expert": 381,
            }.get(game_summary.get("difficulty", "expert"), 381)
            completion = cells / total if total > 0 else 0
            return completion * 100.0