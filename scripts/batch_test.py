#!/usr/bin/env python3
"""批量测试脚本 - 评估AI胜率"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from plugins.minesweeper_agent.agent import MinesweeperAgent

BASE_URL = "http://localhost:8080"

def create_game(diff):
    r = requests.post(f"{BASE_URL}/api/v1/minesweeper/new", json={"difficulty": diff})
    return r.json()["game_id"]

def get_ai_view(gid):
    r = requests.get(f"{BASE_URL}/api/v1/minesweeper/{gid}/ai_view")
    return r.json()["ai_view"]

def move(gid, x, y, action):
    r = requests.post(f"{BASE_URL}/api/v1/minesweeper/{gid}/move",
                      json={"x": x, "y": y, "action": action})
    return r.json()["state"]

def auto_play(difficulty, max_moves=2000):
    gid = create_game(difficulty)
    agent = MinesweeperAgent(use_llm=True)
    moves = 0

    while True:
        state = move(gid, 0, 0, "reveal")  # dummy to refresh state
        if state["result"] != "ongoing":
            return state["result"] == "won", moves

        ai_v = get_ai_view(gid)
        d = agent.decide(ai_v)
        print(f"[{moves+1}] {d['reason']} -> ({d['x']},{d['y']}) {d['action']}")
        state = move(gid, d["x"], d["y"], d["action"])
        moves += 1
        if moves >= max_moves:
            return False, moves

def main():
    diff = sys.argv[1] if len(sys.argv) > 1 else "expert"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    w = 0
    for i in range(n):
        won, m = auto_play(diff)
        w += 1 if won else 0
        print(f"#{i+1}: {'WIN' if won else 'LOSE'} after {m} moves")
    print(f"\n{diff.upper()} {n}局 → 胜率={w/n*100:.1f}% ({w}/{n})")

if __name__ == "__main__":
    main()
