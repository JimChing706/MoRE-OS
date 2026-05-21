#!/usr/bin/env python3
"""MoRE OS Demo — 扫雷自动游玩演示

通过 HTTP API 与游戏服务交互，使用规则推理 AI 自动玩到结束。
用法: python run_demo.py [beginner|intermediate|diff]
"""

import sys
import os
import time
import requests

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

BASE_URL = "http://localhost:8080"


def create_game(difficulty="beginner"):
    resp = requests.post(f"{BASE_URL}/api/v1/minesweeper/new", json={"difficulty": difficulty})
    data = resp.json()
    return data["game_id"]


def get_state(game_id):
    resp = requests.get(f"{BASE_URL}/api/v1/minesweeper/{game_id}/state")
    return resp.json()["state"]


def get_ai_view(game_id):
    resp = requests.get(f"{BASE_URL}/api/v1/minesweeper/{game_id}/ai_view")
    return resp.json()["ai_view"]


def make_move(game_id, x, y, action="reveal"):
    resp = requests.post(
        f"{BASE_URL}/api/v1/minesweeper/{game_id}/move",
        json={"x": x, "y": y, "action": action}
    )
    return resp.json()


def ai_decide(ai_view):
    from plugins.minesweeper_agent.agent import MinesweeperAgent
    agent = MinesweeperAgent(use_llm=False)
    return agent.decide(ai_view)


def auto_play(difficulty="beginner", max_moves=9999):
    print(f"\n{'=' * 60}")
    print(f"开始自动游玩 [{difficulty}]")
    print(f"{'=' * 60}")

    game_id = create_game(difficulty)
    print(f"游戏ID: {game_id}")

    moves = 0
    while True:
        state = get_state(game_id)
        if state["result"] != "ongoing":
            print(f"\n游戏结束: {state['result'].upper()}")
            print(f"步数: {moves}")
            total_cells = state['config']['width'] * state['config']['height']
            non_mine = total_cells - state['config']['num_mines']
            print(f"目标: 翻开 {non_mine} 个非雷格子")
            print(f"实际翻开: {state['cells_revealed']}")
            return state["result"] == "won"

        ai_view = get_ai_view(game_id)
        decision = ai_decide(ai_view)
        x, y, action = decision["x"], decision["y"], decision["action"]
        reason = decision.get("reason", "")

        print(f"[{moves + 1:3d}] 决策: ({x},{y}) {action} | {reason}")

        result = make_move(game_id, x, y, action)
        moves += 1

        if moves >= max_moves:
            print(f"达到最大步数 {max_moves}，放弃")
            return False

        time.sleep(0.05)


if __name__ == "__main__":
    difficulty = sys.argv[1] if len(sys.argv) > 1 else "beginner"
    print(f"开始 {difficulty} 难度自动游玩...")

    won = auto_play(difficulty)
    print(f"\n{'=' * 60}")
    print(f"结果: {'🏆 胜利!' if won else '💥 失败'}")
    print(f"{'=' * 60}")
    sys.exit(0 if won else 1)
