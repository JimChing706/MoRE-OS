"""Minesweeper plugin tool definition - integrated into MoRE OS tool registry"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable, Dict
from dataclasses import dataclass

from more_core.tools.registry import ToolDefinition, ToolResult


# —— Tool Function Implementations ——

async def create_game_tool_impl(params: dict[str, Any]) -> ToolResult:
    """Create new game"""
    difficulty = params.get("difficulty", "beginner")
    custom_config = params.get("custom_config")
    first_click_safe = params.get("first_click_safe", True)

    try:
        from .state_manager import create_game, serialize_game_state
        game = create_game(difficulty, custom_config)

        # Create session
        game_id = f"game_{int(asyncio.get_running_loop().time() * 1000) % 100000}"
        from .state_manager import session_manager
        session = await session_manager.create_session(difficulty, custom_config, first_click_safe)

        state = await session.get_state()
        return ToolResult(
            tool="minesweeper.create_game",
            success=True,
            output={
                "game_id": session.game_id,
                "state": state,
                "message": "Game created via MoRE OS tool",
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.create_game", success=False, error=str(e))


async def reveal_cell_tool_impl(params: dict[str, Any]) -> ToolResult:
    """Reveal cell"""
    x = params.get("x")
    y = params.get("y")
    game_id = params.get("game_id")

    if x is None or y is None or game_id is None:
        return ToolResult(
            tool="minesweeper.reveal",
            success=False,
            error="Missing required parameters: x, y, game_id"
        )

    try:
        from .state_manager import session_manager
        session = await session_manager.get_session(game_id)
        if not session:
            return ToolResult(tool="minesweeper.reveal", success=False, error=f"Game {game_id} not found")

        state = await session.execute_move(x, y, "reveal")
        return ToolResult(
            tool="minesweeper.reveal",
            success=True,
            output={
                "x": x,
                "y": y,
                "result": state["result"],
                "cells_revealed": state["cells_revealed"],
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.reveal", success=False, error=str(e))


async def flag_cell_tool_impl(params: dict[str, Any]) -> ToolResult:
    """Toggle flag on cell"""
    x = params.get("x")
    y = params.get("y")
    game_id = params.get("game_id")

    if x is None or y is None or game_id is None:
        return ToolResult(
            tool="minesweeper.flag",
            success=False,
            error="Missing required parameters: x, y, game_id"
        )

    try:
        from .state_manager import session_manager
        session = await session_manager.get_session(game_id)
        if not session:
            return ToolResult(tool="minesweeper.flag", success=False, error=f"Game {game_id} not found")

        state = await session.execute_move(x, y, "flag")
        return ToolResult(
            tool="minesweeper.flag",
            success=True,
            output={
                "x": x,
                "y": y,
                "flags_placed": state["flags_placed"],
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.flag", success=False, error=str(e))


async def get_state_tool_impl(params: dict[str, Any]) -> ToolResult:
    """Get game state"""
    game_id = params.get("game_id")

    if not game_id:
        return ToolResult(tool="minesweeper.get_state", success=False, error="game_id required")

    try:
        from .state_manager import session_manager
        session = await session_manager.get_session(game_id)
        if not session:
            return ToolResult(tool="minesweeper.get_state", success=False, error="Game not found")

        state = await session.get_state()
        return ToolResult(
            tool="minesweeper.get_state",
            success=True,
            output={
                "game_id": game_id,
                "state": {
                    "result": state["result"],
                    "cells_revealed": state["cells_revealed"],
                    "flags_placed": state["flags_placed"],
                    "config": state["config"],
                },
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.get_state", success=False, error=str(e))


async def auto_play_tool_impl(params: dict[str, Any]) -> ToolResult:
    """AI auto-play a game (blocking until ends)"""
    difficulty = params.get("difficulty", "beginner")
    max_moves = params.get("max_moves", 999)
    use_ai = params.get("use_ai", True)

    try:
        from .state_manager import create_game, session_manager
        import random
        import time

        # Create temporary game session
        game = create_game(difficulty)
        game_id = await session_manager.create_session(difficulty)
        session = await session_manager.get_session(game_id)

        # First click (center)
        mid_x = session.game.config.width // 2
        mid_y = session.game.config.height // 2
        await session.execute_move(mid_x, mid_y, "reveal")
        moves = 1

        # Auto loop
        while not session.game.is_game_over() and moves < 1000:
            state = await session.get_state()
            ai_view = state.get("ai_view", {})

            if use_ai:
                from plugins.minesweeper_agent.agent import MinesweeperAgent
                agent = MinesweeperAgent(use_llm=False)
                decision = agent.decide(ai_view)
                x, y, action = decision["x"], decision["y"], decision["action"]
            else:
                hidden = []
                for gx in range(session.game.config.width):
                    for gy in range(session.game.config.height):
                        cell = state["cells"][gx][gy]
                        if cell["state"] == "hidden":
                            hidden.append((gx, gy))
                if not hidden:
                    break
                import random
                x, y = random.choice(hidden)
                action = "reveal"

            await session.execute_move(x, y, action)
            moves += 1

        final_state = await session.get_state()
        result = final_state["result"]

        # Calculate performance score (0-100)
        total_cells = final_state["config"]["width"] * final_state["config"]["height"] - final_state["config"]["num_mines"]
        if result == "won":
            score = max(0.0, 100.0 - moves * 0.2)  # Win base 100, subtract 0.2 per move
        else:
            completion = final_state["cells_revealed"] / total_cells if total_cells > 0 else 0
            score = completion * 100.0

        # Record to EvolutionArchive
        try:
            # Get from plugin context (injected on registration)
            from . import session_manager as _sm
            plugin_ctx = getattr(_sm, "_plugin_context", None)
            if plugin_ctx:
                from more_core.evolution.archive import EvolvedAgent
                agent_id = plugin_ctx.core.evolution_archive.new_id("minesweeper_agent")
                evolved = EvolvedAgent(
                    id=agent_id,
                    parent_id=None,
                    generation=0,
                    branch="rule_based",
                    code="ReasoningEngine+ProbabilityEngine",
                    performance=score,
                    description=f"{difficulty} {result} in {moves} moves",
                    created_at=time.time(),
                    verified=False,
                )
                plugin_ctx.core.evolution_archive.add(evolved)
        except Exception:
            pass  # Evolutionary recording is best-effort

        await session_manager.remove_session(game_id)

        return ToolResult(
            tool="minesweeper.auto_play",
            success=True,
            output={
                "result": result,
                "moves": moves,
                "elapsed_seconds": final_state["elapsed_seconds"],
                "win": result == "won",
                "score": round(score, 2),
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.auto_play", success=False, error=str(e))


# —— Tool Definition List ——

TOOLS = [
    ToolDefinition(
        name="minesweeper.create_game",
        description="Create new minesweeper game instance",
        parameters_schema={
            "type": "object",
            "properties": {
                "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "expert", "custom"], "default": "beginner"},
                "custom_config": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                        "mines": {"type": "integer"},
                    },
                },
                "first_click_safe": {"type": "boolean", "default": True},
            },
        },
        handler=create_game_tool_impl,
        requires_sandbox=False,
        tags=("game",),
    ),
    ToolDefinition(
        name="minesweeper.reveal",
        description="Reveal cell at specified coordinates",
        parameters_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate (0-based)"},
                "y": {"type": "integer", "description": "Y coordinate (0-based)"},
                "game_id": {"type": "string", "description": "Game ID"},
            },
            "required": ["x", "y", "game_id"],
        },
        handler=reveal_cell_tool_impl,
        requires_sandbox=False,
        tags=("game",),
    ),
    ToolDefinition(
        name="minesweeper.flag",
        description="Toggle flag on cell",
        parameters_schema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "game_id": {"type": "string"},
            },
            "required": ["x", "y", "game_id"],
        },
        handler=flag_cell_tool_impl,
        requires_sandbox=False,
        tags=("game",),
    ),
    ToolDefinition(
        name="minesweeper.get_state",
        description="Get current game state",
        parameters_schema={
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
            },
            "required": ["game_id"],
        },
        handler=get_state_tool_impl,
        requires_sandbox=False,
        tags=("game", "query"),
    ),
    ToolDefinition(
        name="minesweeper.auto_play",
        description="AI auto-play a game (blocking until ends)",
        parameters_schema={
            "type": "object",
            "properties": {
                "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "expert"], "default": "beginner"},
                "max_moves": {"type": "integer", "default": 999, "description": "Maximum move limit"},
                "use_ai": {"type": "boolean", "default": True, "description": "Use AI agent (otherwise random)"},
            },
        },
        handler=auto_play_tool_impl,
        requires_sandbox=False,
        tags=("ai", "autoplay"),
    ),
]


def register_tools(registry) -> None:
    """Register minesweeper tools to MoRE OS tool registry"""
    for tool_def in TOOLS:
        registry.register(tool_def)