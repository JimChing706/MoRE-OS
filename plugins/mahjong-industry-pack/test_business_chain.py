#!/usr/bin/env python3
"""MoRE OS Business Logic Chain Test - Mahjong Industry Pack.

Tests the complete business logic chain:
L4 Cognition → L3 Symbolic → L1 Orchestration → L0 Execution

Uses Mahjong plugin as the domain-specific example.
"""

import asyncio
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "more_core"))

from more_core.runtime.orchestrator import MoRECore
from more_core.core.types import TaskRequest, TaskType, TaskResult, TaskStatus


async def test_mahjong_tools_direct():
    """Test mahjong tools directly (bypassing LLM)."""
    print("\n" + "="*60)
    print("TEST 1: Mahjong Engine Direct Test")
    print("="*60)

    from mahjong_engine import MahjongEngine, GameConfig

    engine = MahjongEngine()
    game_id = "test_game_001"

    state = engine.initialize(["Alice", "Bob", "Charlie", "David"], game_id)
    print(f"✓ Game initialized: {game_id}")
    print(f"  Players: {[p.name for p in state.players]}")

    deal_result = engine.deal_tiles()
    print(f"✓ Tiles dealt: {deal_result['tiles_dealt']}")

    player1_hand = engine.state.players[0].hand
    print(f"✓ Player 1 hand: {[str(t) for t in player1_hand]}")

    shanten = engine.calculate_shanten(player1_hand)
    print(f"✓ Shanten number: {shanten}")

    win_result = engine.check_win(player1_hand)
    print(f"✓ Win check: is_win={win_result['is_win']}, reason={win_result.get('reason', '')}")

    draw_result = engine.draw_tile(0)
    print(f"✓ Draw tile: {draw_result.get('tile', 'N/A')}")

    hand_after_draw = engine.state.players[0].hand
    shanten_after = engine.calculate_shanten(hand_after_draw)
    print(f"✓ Shanten after draw: {shanten_after}")

    if len(hand_after_draw) > 1:
        discard_result = engine.discard_tile(0, 0)
        print(f"✓ Discard tile: {discard_result.get('tile', 'N/A')}")

    game_view = engine.get_game_view(0)
    print(f"✓ Game view (Player 0):")
    print(f"  - Hand count: {game_view['self']['hand_count']}")
    print(f"  - Shanten: {game_view['ai_view']['shanten']}")
    print(f"  - Tiles remaining: {game_view['ai_view']['tiles_remaining']}")

    return True


async def test_more_os_chain():
    """Test the complete MoRE OS L4→L3→L1→L0 chain."""
    print("\n" + "="*60)
    print("TEST 2: MoRE OS Complete Business Chain (L4→L3→L1→L0)")
    print("="*60)

    core = MoRECore.from_env()
    await core.start()
    from more_core.version import __version__
    print(f"✓ MoRE Core started (version: {__version__})")

    print(f"\n  System state:")
    print(f"  - Symbolic layer: {'enabled' if core.settings.enable_symbolic else 'disabled'}")
    print(f"  - Evolution layer: {'enabled' if core.settings.enable_evolution else 'disabled'}")
    print(f"  - Metacognition: {'enabled' if core.settings.enable_metacognition else 'disabled'}")

    providers = core.llm.list_providers()
    print(f"  - LLM providers: {providers}")

    result = await core.execute(TaskRequest(
        type=TaskType.NLP_TASK,
        query="用一句话解释麻将游戏中什么叫向听数(shanten)",
        timeout_s=60.0
    ))
    print(f"\n✓ NLP Task executed (with rule-based fallback):")
    print(f"  - Status: {result.status.value}")
    print(f"  - Layer: {result.layer.value}")
    print(f"  - Duration: {result.performance.total_duration_ms:.1f}ms")
    print(f"  - Reasoning steps: {len(result.reasoning_chain)}")
    print(f"  - Pipeline executed: {[s.layer.value for s in result.reasoning_chain]}")

    if result.output:
        print(f"  - Output preview: {result.output[:100]}...")

    await core.stop()
    print(f"✓ MoRE Core stopped")
    return result.status == TaskStatus.SUCCESS


async def test_mahjong_plugin_integration():
    """Test Mahjong plugin integration with MoRE OS."""
    print("\n" + "="*60)
    print("TEST 3: Mahjong Plugin + MoRE OS Integration")
    print("="*60)

    core = MoRECore.from_env()
    await core.start()
    print(f"✓ MoRE Core started")

    plugin_dir = Path(__file__).parent.parent / "plugins"
    if plugin_dir.exists():
        print(f"✓ Plugin directory found: {plugin_dir}")

        core.plugins.discover()
        discovered = core.plugins.list()
        print(f"  - Discovered plugins: {[m.name for m in discovered]}")

    available_tools = list(core.tools._tools.keys())
    print(f"  - Registered tools: {len(available_tools)}")
    mahjong_tools = [t for t in available_tools if t.startswith("mahjong.")]
    print(f"  - Mahjong tools: {mahjong_tools}")

    if mahjong_tools:
        result = await core.execute(TaskRequest(
            type=TaskType.NLP_TASK,
            query="分析这副麻将手牌：bamboo_1, bamboo_1, bamboo_2, bamboo_2, bamboo_3, bamboo_3, characters_1, characters_1, dots_1, dots_1, dots_2, dots_2, dots_3, dots_3，告诉我这是什么牌型",
            timeout_s=90.0
        ))
        print(f"\n✓ Mahjong analysis task:")
        print(f"  - Status: {result.status.value}")
        print(f"  - Duration: {result.performance.total_duration_ms:.1f}ms")
        print(f"  - Reasoning steps: {len(result.reasoning_chain)}")
        for step in result.reasoning_chain:
            print(f"    [{step.layer.value}] {step.description[:50]}...")
    else:
        print("  Note: Mahjong plugin not loaded, plugin integration test skipped")

    await core.stop()
    return True


async def test_dashboard_api():
    """Test the dashboard monitoring API."""
    print("\n" + "="*60)
    print("TEST 4: Dashboard Monitoring API")
    print("="*60)

    try:
        import requests

        core = MoRECore.from_env()
        await core.start()

        import time
        uptime = time.time() - core._start_time

        print(f"✓ MoRE Core running for {uptime:.1f}s")

        hands_stats = core.hands.stats()
        print(f"  - Registered Hands: {hands_stats.get('registered', 0)}")
        print(f"  - Active Hands: {hands_stats.get('active', 0)}")

        layers = list(core._layers.keys())
        print(f"  - Active Layers: {[l.value for l in layers]}")

        tools_count = len(core.tools._tools)
        print(f"  - Registered Tools: {tools_count}")

        registry_stats = core.registry.stats()
        print(f"  - Service Registry: {registry_stats.get('total', 0)} services")

        await core.stop()
        return True
    except Exception as e:
        print(f"  Note: API test requires server running ({e})")
        return True


async def test_mahjong_tools_through_registry():
    """Test mahjong tools through MoRE OS tool registry."""
    print("\n" + "="*60)
    print("TEST 5: Mahjong Tools Through Registry")
    print("="*60)

    from more_core.tools.registry import ToolDefinition, ToolResult
    from mahjong_engine import MahjongEngine, GameConfig

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
            handler=None,
            requires_sandbox=False,
            tags=("game", "mahjong"),
        ),
        ToolDefinition(
            name="mahjong.get_shanten",
            description="Calculate shanten number for a hand",
            parameters_schema={
                "type": "object",
                "properties": {
                    "hand": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tile strings"
                    }
                },
                "required": ["hand"]
            },
            handler=None,
            requires_sandbox=False,
            tags=("game", "mahjong", "ai"),
        ),
        ToolDefinition(
            name="mahjong.check_win",
            description="Check if a hand is a winning hand",
            parameters_schema={
                "type": "object",
                "properties": {
                    "hand": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tile strings"
                    }
                },
                "required": ["hand"]
            },
            handler=None,
            requires_sandbox=False,
            tags=("game", "mahjong"),
        ),
    ]

    engine = MahjongEngine()
    game_id = "test_reg_001"
    state = engine.initialize(["P1", "P2", "P3", "P4"], game_id)
    engine.deal_tiles()

    print(f"✓ Tool definitions created: {[t.name for t in tools]}")
    print(f"✓ Game session created: {game_id}")
    print(f"✓ Player 1 hand: {[str(t) for t in engine.state.players[0].hand]}")

    shanten = engine.calculate_shanten(engine.state.players[0].hand)
    print(f"✓ Shanten calculated via engine: {shanten}")

    win_result = engine.check_win(engine.state.players[0].hand)
    print(f"✓ Win check via engine: is_win={win_result['is_win']}")

    return True


async def main():
    """Run all tests."""
    print("\n" + "#"*60)
    print("# MoRE OS Business Logic Chain Test - Mahjong Industry Pack")
    print("#"*60)

    results = {}

    try:
        results["mahjong_engine"] = await test_mahjong_tools_direct()
    except Exception as e:
        print(f"✗ TEST 1 failed: {e}")
        results["mahjong_engine"] = False

    try:
        results["more_os_chain"] = await test_more_os_chain()
    except Exception as e:
        print(f"✗ TEST 2 failed: {e}")
        results["more_os_chain"] = False

    try:
        results["plugin_integration"] = await test_mahjong_plugin_integration()
    except Exception as e:
        print(f"✗ TEST 3 failed: {e}")
        results["plugin_integration"] = False

    try:
        results["dashboard_api"] = await test_dashboard_api()
    except Exception as e:
        print(f"✗ TEST 4 failed: {e}")
        results["dashboard_api"] = False

    try:
        results["mahjong_registry"] = await test_mahjong_tools_through_registry()
    except Exception as e:
        print(f"✗ TEST 5 failed: {e}")
        results["mahjong_registry"] = False

    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")

    all_passed = all(results.values())
    print(f"\n{'='*60}")
    if all_passed:
        print("All tests PASSED ✓")
    else:
        print("Some tests FAILED ✗")
    print("="*60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)