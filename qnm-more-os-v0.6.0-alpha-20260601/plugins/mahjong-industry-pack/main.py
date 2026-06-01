"""QNMing MoRE OS — Mahjong Industry Pack.

This plugin demonstrates how a domain-specific application (mahjong game AI)
integrates with the MoRE OS kernel as an Industry Pack.

It provides:
- Mahjong game engine with rules
- AI strategy tools for autonomous play
- Hand registration for scheduled execution
"""

from __future__ import annotations

import uuid
from typing import Any

from more_core.plugins.sdk import PluginBase
from .mahjong_engine import MahjongEngine, GameConfig


class Plugin(PluginBase):
    NAME = "mahjong-industry-pack"
    VERSION = "0.5.0"
    DESCRIPTION = "Mahjong Strategy AI - 广东麻将行业插件"
    AUTHOR = "QNMing MoRE Team"
    CAPABILITIES = ("mahjong_strategy", "game_ai", "multiplayer")
    DEPENDENCIES = ()

    def __init__(self):
        super().__init__()
        self._engine: MahjongEngine | None = None
        self._current_game: str | None = None

    async def activate(self, ctx: Any) -> None:
        """Register mahjong-specific tools and capabilities."""
        await super().activate(ctx)
        self._ctx = ctx

        self._register_tools(ctx.core.tools)
        self._register_hand(ctx.core.hands, ctx.core.hand_registry)

        ctx.logger.info("Mahjong Industry Pack activated")

    async def deactivate(self) -> None:
        """Clean up mahjong plugin resources."""
        self._engine = None
        self._current_game = None
        await super().deactivate()

    def capabilities(self) -> dict[str, Any]:
        base = super().capabilities()
        base.update({
            "game_modes": ["guangdong", "sichuan", "taiwan", "japanese"],
            "ai_strategies": ["rule_based", "tenpai_optimized"],
            "supported_yaku": ["seven_pairs", "qingyi", "pinghu", "duanqiu"]
        })
        return base

    def _register_tools(self, tool_registry) -> None:
        """Register mahjong tools."""
        from more_core.tools.registry import ToolDefinition

        tools = [
            ToolDefinition(
                name="mahjong.create_game",
                description="Create a new mahjong game session",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "player_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of player names (max 4)"
                        },
                        "rule_type": {
                            "type": "string",
                            "default": "guangdong",
                            "enum": ["guangdong", "sichuan", "taiwan", "japanese"]
                        }
                    },
                    "required": ["player_names"]
                },
                handler=self._create_game_impl,
                requires_sandbox=False,
                tags=("game", "mahjong"),
            ),
            ToolDefinition(
                name="mahjong.get_state",
                description="Get current game state for a player",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"},
                        "player_id": {"type": "integer", "default": 0}
                    },
                    "required": ["game_id"]
                },
                handler=self._get_state_impl,
                requires_sandbox=False,
                tags=("game", "mahjong"),
            ),
            ToolDefinition(
                name="mahjong.deal",
                description="Deal tiles to all players",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"}
                    },
                    "required": ["game_id"]
                },
                handler=self._deal_impl,
                requires_sandbox=False,
                tags=("game", "mahjong"),
            ),
            ToolDefinition(
                name="mahjong.draw",
                description="Draw a tile for a player",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"},
                        "player_id": {"type": "integer", "default": 0}
                    },
                    "required": ["game_id"]
                },
                handler=self._draw_impl,
                requires_sandbox=False,
                tags=("game", "mahjong"),
            ),
            ToolDefinition(
                name="mahjong.discard",
                description="Discard a tile from player's hand",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"},
                        "player_id": {"type": "integer", "default": 0},
                        "tile_index": {"type": "integer"}
                    },
                    "required": ["game_id", "tile_index"]
                },
                handler=self._discard_impl,
                requires_sandbox=False,
                tags=("game", "mahjong"),
            ),
            ToolDefinition(
                name="mahjong.check_win",
                description="Check if player's hand is a winning hand",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"},
                        "player_id": {"type": "integer", "default": 0}
                    },
                    "required": ["game_id"]
                },
                handler=self._check_win_impl,
                requires_sandbox=False,
                tags=("game", "mahjong", "ai"),
            ),
            ToolDefinition(
                name="mahjong.suggest_discard",
                description="AI suggests the best tile to discard",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "game_id": {"type": "string"},
                        "player_id": {"type": "integer", "default": 0}
                    },
                    "required": ["game_id"]
                },
                handler=self._suggest_discard_impl,
                requires_sandbox=False,
                tags=("game", "mahjong", "ai"),
            ),
        ]

        for tool in tools:
            tool_registry.register(tool)

    def _register_hand(self, hand_manager, hand_registry) -> None:
        """Register Mahjong as an autonomous Hand."""
        from more_core.hands.builtins import register_hand_function

        async def mahjong_hand_run(context: dict[str, Any] | None = None) -> dict[str, Any]:
            try:
                engine = MahjongEngine()
                game_id = str(uuid.uuid4())[:8]
                state = engine.initialize(["Player1", "Player2", "Player3", "Player4"], game_id)
                deal_result = engine.deal_tiles()

                player1_hand = engine.state.players[0].hand
                shanten = engine.calculate_shanten(player1_hand)
                win_check = engine.check_win(player1_hand)

                return {
                    "success": True,
                    "game_id": game_id,
                    "tiles_dealt": deal_result["tiles_dealt"],
                    "player1_hand": [str(t) for t in player1_hand],
                    "shanten": shanten,
                    "is_win": win_check["is_win"],
                    "win_reason": win_check.get("reason", "")
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        register_hand_function(
            hand_registry,
            "mahjong",
            "麻将游戏",
            "game",
            "*/30 * * * *",
            mahjong_hand_run,
            description="自动运行麻将游戏测试，验证 MoRE OS 业务链路",
            tools=["mahjong.create_game", "mahjong.get_state", "mahjong.check_win"],
            skills=["mahjong_rules", "strategy"]
        )

    async def _create_game_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult
        try:
            player_names = params.get("player_names", ["Player1", "Player2", "Player3", "Player4"])
            rule_type = params.get("rule_type", "guangdong")

            self._engine = MahjongEngine(GameConfig(rule_type=rule_type))
            self._current_game = str(uuid.uuid4())[:8]
            self._engine.initialize(player_names, self._current_game)

            return ToolResult(
                tool="mahjong.create_game",
                success=True,
                output={
                    "game_id": self._current_game,
                    "players": player_names,
                    "rule_type": rule_type,
                    "status": "ready"
                }
            )
        except Exception as e:
            from more_core.tools.registry import ToolResult
            return ToolResult(tool="mahjong.create_game", success=False, error=str(e))

    async def _get_state_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult
        try:
            game_id = params.get("game_id", self._current_game)
            player_id = params.get("player_id", 0)

            if not self._engine or not game_id:
                return ToolResult(tool="mahjong.get_state", success=False, error="No active game")

            view = self._engine.get_game_view(player_id)
            return ToolResult(tool="mahjong.get_state", success=True, output=view)
        except Exception as e:
            return ToolResult(tool="mahjong.get_state", success=False, error=str(e))

    async def _deal_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult as TR
        try:
            if not self._engine:
                return TR(tool="mahjong.deal", success=False, error="No active game")

            result = self._engine.deal_tiles()
            return TR(tool="mahjong.deal", success=True, output=result)
        except Exception as e:
            return TR(tool="mahjong.deal", success=False, error=str(e))

    async def _draw_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult as TR
        try:
            if not self._engine:
                return TR(tool="mahjong.draw", success=False, error="No active game")

            player_id = params.get("player_id", 0)
            result = self._engine.draw_tile(player_id)
            return TR(tool="mahjong.draw", success=True, output=result)
        except Exception as e:
            return TR(tool="mahjong.draw", success=False, error=str(e))

    async def _discard_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult as TR
        try:
            if not self._engine:
                return TR(tool="mahjong.discard", success=False, error="No active game")

            player_id = params.get("player_id", 0)
            tile_index = params.get("tile_index", 0)
            result = self._engine.discard_tile(player_id, tile_index)
            return TR(tool="mahjong.discard", success=True, output=result)
        except Exception as e:
            return TR(tool="mahjong.discard", success=False, error=str(e))

    async def _check_win_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult as TR
        try:
            if not self._engine:
                return TR(tool="mahjong.check_win", success=False, error="No active game")

            player_id = params.get("player_id", 0)
            hand = self._engine.state.players[player_id].hand
            result = self._engine.check_win(hand)
            return TR(tool="mahjong.check_win", success=True, output=result)
        except Exception as e:
            return TR(tool="mahjong.check_win", success=False, error=str(e))

    async def _suggest_discard_impl(self, params: dict[str, Any]) -> "ToolResult":
        from more_core.tools.registry import ToolResult as TR
        try:
            if not self._engine:
                return TR(tool="mahjong.suggest_discard", success=False, error="No active game")

            player_id = params.get("player_id", 0)
            hand = self._engine.state.players[player_id].hand

            best_shanten = float('inf')
            best_tile_idx = 0

            for i, tile in enumerate(hand):
                test_hand = hand[:i] + hand[i+1:]
                shanten = self._engine.calculate_shanten(test_hand)
                if shanten < best_shanten:
                    best_shanten = shanten
                    best_tile_idx = i

            return TR(
                tool="mahjong.suggest_discard",
                success=True,
                output={
                    "suggested_tile": str(hand[best_tile_idx]),
                    "tile_index": best_tile_idx,
                    "expected_shanten": best_shanten
                }
            )
        except Exception as e:
            return TR(tool="mahjong.suggest_discard", success=False, error=str(e))


ToolResult = __import__("more_core.tools.registry", fromlist=["ToolResult"]).ToolResult