#!/usr/bin/env python3
"""扫雷游戏自动游玩演示

通过HTTP API与游戏服务交互,使用规则推理AI自动玩到结束。
"""

import sys
import os

# 将项目根目录加入Python路径,以便导入plugins.*模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import requests
import time

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
    """使用本地规则推理AI决策"""
    from plugins.minesweeper_agent.agent import MinesweeperAgent
    agent = MinesweeperAgent(use_llm=False)
    decision = agent.decide(ai_view)
    return decision


def auto_play(difficulty="beginner", max_moves=9999):
    print(f"\n=== 开始自动游玩 [{difficulty}] ===")
    game_id = create_game(difficulty)
    print(f"游戏ID: {game_id}")

    moves = 0
    while True:
        state = get_state(game_id)
        if state["result"] != "ongoing":
            print(f"\n游戏结束: {state['result'].upper()}")
            print(f"总步数: {moves}")
            total_cells = state['config']['width'] * state['config']['height']
            non_mine = total_cells - state['config']['num_mines']
            print(f"目标: 翻开 {non_mine} 个非雷格子")
            print(f"实际翻开: {state['cells_revealed']}")
            return state["result"] == "won"

        ai_view = get_ai_view(game_id)
        decision = ai_decide(ai_view)
        x, y, action = decision["x"], decision["y"], decision["action"]
        reason = decision.get("reason", "")

        print(f"[{moves+1:3d}] 决策: ({x},{y}) {action} | {reason}")

        result = make_move(game_id, x, y, action)
        state = result["state"]
        moves += 1

        if moves >= max_moves:
            print("达到最大步数限制,放弃")
            return False

        time.sleep(0.05)  # 稍微放慢,便于观察


if __name__ == "__main__":
    difficulty = sys.argv[1] if len(sys.argv) > 1 else "beginner"
    print(f"开始 {difficulty} 难度自动游玩...")

    won = auto_play(difficulty)
    print(f"\n结果: {'胜利!' if won else '失败'}")
