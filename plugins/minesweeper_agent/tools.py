"""Minesweeper AI agent tool definition"""

from __future__ import annotations

from typing import Any, Dict
import asyncio

from more_core.tools.registry import ToolDefinition, ToolResult
from .agent import MinesweeperAgent


# Global agent instance (lazy load)
_agent_instance: MinesweeperAgent | None = None


def get_agent(use_llm: bool = False) -> MinesweeperAgent:
    """Get or create AI agent instance"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MinesweeperAgent(use_llm=use_llm)
    return _agent_instance


async def agent_decide_tool_impl(params: dict[str, Any]) -> ToolResult:
    """AI decision tool - analyze board and suggest next move"""
    ai_view = params.get("ai_view")
    game_id = params.get("game_id")
    use_llm = params.get("use_llm", False)

    if not ai_view or not game_id:
        return ToolResult(
            tool="minesweeper.agent.decide",
            success=False,
            error="Missing required parameters: ai_view, game_id"
        )

    try:
        agent = get_agent(use_llm=use_llm)
        # Run decision in executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        decision = await loop.run_in_executor(None, agent.decide, ai_view)

        decision["game_id"] = game_id
        return ToolResult(
            tool="minesweeper.agent.decide",
            success=True,
            output=decision,
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.agent.decide", success=False, error=str(e))


async def auto_play_full_tool_impl(params: dict[str, Any]) -> ToolResult:
    """Full auto-play tool - create game and play to end"""
    difficulty = params.get("difficulty", "beginner")
    use_ai = params.get("use_ai", True)

    try:
        from more_core_plugins.minesweeper_game.state_manager import session_manager, create_game

        # Create game session
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
                agent = get_agent(use_llm=False)  # Auto mode disables LLM for speed
                decision = agent.decide(ai_view)
                x, y, action = decision["x"], decision["y"], decision["action"]
            else:
                # Random strategy
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
        await session_manager.remove_session(game_id)

        return ToolResult(
            tool="minesweeper.agent.auto_play_full",
            success=True,
            output={
                "game_id": game_id,
                "result": final_state["result"],
                "moves": moves,
                "win": final_state["result"] == "won",
                "cells_revealed": final_state["cells_revealed"],
            },
        )
    except Exception as e:
        return ToolResult(tool="minesweeper.agent.auto_play_full", success=False, error=str(e))


# —— Tool Definition List ——

TOOLS = [
    ToolDefinition(
        name="minesweeper.agent.decide",
        description="AI agent analyzes current board and suggests next move",
        parameters_schema={
            "type": "object",
            "properties": {
                "ai_view": {
                    "type": "object",
                    "description": "AI view game state (visible cells, flags, etc)",
                },
                "game_id": {"type": "string", "description": "Game ID"},
                "use_llm": {"type": "boolean", "default": False, "description": "Use LLM enhancement"},
            },
            "required": ["ai_view", "game_id"],
        },
        handler=agent_decide_tool_impl,
        requires_sandbox=False,
        tags=("ai", "decision"),
    ),
    ToolDefinition(
        name="minesweeper.agent.auto_play_full",
        description="AI auto-plays from creation to end (full game)",
        parameters_schema={
            "type": "object",
            "properties": {
                "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "expert"], "default": "beginner"},
                "use_ai": {"type": "boolean", "default": True, "description": "Use AI strategy (otherwise random)"},
            },
        },
        handler=auto_play_full_tool_impl,
        requires_sandbox=False,
        tags=("ai", "autoplay", "full_game"),
    ),
]


def register_tools(registry) -> None:
    """Register AI agent tools"""
    for tool_def in TOOLS:
        registry.register(tool_def)