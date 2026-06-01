"""Minesweeper AI agent - hybrid reasoning strategy

Integrates:
- Basic rule reasoning (single/double variable constraint satisfaction)
- Probability reasoning (conditional probability calculation)
- LLM enhanced strategy (optional)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, List, Tuple
import json


@dataclass
class CellInfo:
    """Cell info from AI perspective (hidden)"""
    x: int
    y: int
    is_revealed: bool
    is_flagged: bool
    adjacent_mines: int = 0  # Known (if revealed)
    adjacent_unknown: int = 0  # Unknown cells count
    adjacent_flags: int = 0  # Flagged count
    probability: float = 0.5  # Mine probability estimate


class ReasoningEngine:
    """Rule reasoning engine - implements basic minesweeper logic"""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    def get_neighbors(self, x: int, y: int) -> List[Tuple[int, int]]:
        """Get 8-neighbor coordinates"""
        neighbors = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    neighbors.append((nx, ny))
        return neighbors

    def analyze_cell(self, grid: List[List[CellInfo]], x: int, y: int) -> Optional[dict]:
        """Analyze single number cell, return reasoning result"""
        cell = grid[x][y]
        if not cell.is_revealed or cell.adjacent_mines == 0:
            return None

        neighbors = self.get_neighbors(x, y)
        hidden = [(nx, ny) for nx, ny in neighbors if not grid[nx][ny].is_revealed and not grid[nx][ny].is_flagged]
        flags = sum(1 for nx, ny in neighbors if grid[nx][ny].is_flagged)

        remaining = cell.adjacent_mines - flags
        if remaining < 0:
            return None  # Flag error (should not happen)

        # Rule 1: remaining mines = 0 -> all hidden cells are safe
        if remaining == 0 and hidden:
            return {"type": "safe", "cells": hidden, "reason": f"No unmarked mines around ({x},{y})"}

        # Rule 2: remaining mines = hidden cells count -> all hidden cells are mines
        if remaining == len(hidden) and remaining > 0:
            return {"type": "mine", "cells": hidden, "reason": f"Remaining {remaining} mines around ({x},{y}) equals unknown cells"}

        return None

    def find_safe_moves(self, grid: List[List[CellInfo]]) -> List[Tuple[int, int]]:
        """Find definite safe cells (enhanced)"""
        safe_moves = []
        # Step 1: Single cell basic rule
        for x in range(self.width):
            for y in range(self.height):
                result = self.analyze_cell(grid, x, y)
                if result and result["type"] == "safe":
                    safe_moves.extend(result["cells"])
        # Step 2: Cross analysis (1.5 rule)
        cross = self.cross_analysis(grid)
        if cross and cross["type"] == "safe":
            safe_moves.extend(cross["cells"])
        # Deduplicate
        return list(set(safe_moves))

    def find_mines(self, grid: List[List[CellInfo]]) -> List[Tuple[int, int]]:
        """Find definite mine cells (enhanced)"""
        mines = []
        # Step 1: Single cell basic rule
        for x in range(self.width):
            for y in range(self.height):
                result = self.analyze_cell(grid, x, y)
                if result and result["type"] == "mine":
                    mines.extend(result["cells"])
        # Step 2: Cross analysis (1.5 rule)
        cross = self.cross_analysis(grid)
        if cross and cross["type"] == "mine":
            mines.extend(cross["cells"])
        # Deduplicate
        return list(set(mines))

    def cross_analysis(self, grid: List[List[CellInfo]]) -> Optional[dict]:
        """Cross analysis - subset constraint reasoning (1.5 rule)"""
        # Collect numbered cell info
        numbered = []
        for x in range(self.width):
            for y in range(self.height):
                cell = grid[x][y]
                if cell.is_revealed and cell.adjacent_mines > 0:
                    neighbors = self.get_neighbors(x, y)
                    hidden = []
                    flag_cnt = 0
                    for nx, ny in neighbors:
                        nc = grid[nx][ny]
                        if nc.is_flagged:
                            flag_cnt += 1
                        elif not nc.is_revealed:
                            hidden.append((nx, ny))
                    rem = cell.adjacent_mines - flag_cnt
                    if hidden and rem > 0:
                        numbered.append({"pos": (x,y), "rem": rem, "hidden": set(hidden)})

        # Pairwise comparison: A ⊂ B or B ⊂ A
        for i, a in enumerate(numbered):
            for j, b in enumerate(numbered):
                if i >= j:
                    continue
                a_set = a["hidden"]; b_set = b["hidden"]
                if a_set.issubset(b_set) and len(a_set) < len(b_set):
                    diff = b_set - a_set
                    dr = b["rem"] - a["rem"]
                    if dr == 0:
                        return {"type":"safe","cells":list(diff),
                                "reason":f"Subset: B remaining mines all in A"}
                    if dr == len(diff):
                        return {"type":"mine","cells":list(diff),
                                "reason":f"Subset: difference all mines ({dr})"}
                if b_set.issubset(a_set) and len(b_set) < len(a_set):
                    diff = a_set - b_set
                    dr = a["rem"] - b["rem"]
                    if dr == 0:
                        return {"type":"safe","cells":list(diff),
                                "reason":f"Subset: A remaining mines all in B"}
                    if dr == len(diff):
                        return {"type":"mine","cells":list(diff),
                                "reason":f"Subset: difference all mines ({dr})"}
        return None


class ProbabilityEngine:
    """Probability reasoning engine - simplified conditional probability"""

    def __init__(self, width: int, height: int, total_mines: int):
        self.width = width
        self.height = height
        self.total_mines = total_mines

    def calculate_basic_probability(self, grid: List[List[CellInfo]]) -> Optional[Tuple[int, int]]:
        """Calculate mine probability for each hidden cell, return most likely safe cell"""
        hidden_cells = []
        for x in range(self.width):
            for y in range(self.height):
                cell = grid[x][y]
                if not cell.is_revealed and not cell.is_flagged:
                    hidden_cells.append((x, y))

        if not hidden_cells:
            return None

        # Each hidden cell accumulates "pressure value": mine demand from surrounding numbered cells
        scores = {pos: 0.0 for pos in hidden_cells}

        for hx, hy in hidden_cells:
            # Iterate through surrounding numbered cells
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = hx + dx, hy + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        ncell = grid[nx][ny]
                        if ncell.is_revealed and ncell.adjacent_mines > 0:
                            # Calculate how many unrevealed cells around this numbered cell
                            hidden_around = 0
                            for dxx in (-1, 0, 1):
                                for dyy in (-1, 0, 1):
                                    if dxx == 0 and dyy == 0:
                                        continue
                                    nnx, nny = nx + dxx, ny + dyy
                                    if 0 <= nnx < self.width and 0 <= nny < self.height:
                                        nc = grid[nnx][nny]
                                        if not nc.is_revealed and not nc.is_flagged:
                                            hidden_around += 1
                            if hidden_around > 0:
                                share = ncell.adjacent_mines / hidden_around
                                scores[(hx, hy)] += share

        # Select lowest pressure value (likely fewest mines)
        if any(scores.values()):
            best = min(scores, key=scores.get)
            return best

        # No numbered cell reference, random
        import random
        return random.choice(hidden_cells)


class LLMAdvisor:
    """LLM strategy advisor - utilizes MoRE OS LLM Manager"""

    def __init__(self, llm_manager=None, model: str = "llama3.2:3b"):
        """
        Args:
            llm_manager: MoRE OS LLMManager instance (preferred)
            model: Fallback model name (used for direct calls)
        """
        self.llm_manager = llm_manager
        self.model = model
        self.use_manager = llm_manager is not None

    async def suggest_move(self, grid_summary: str, total_mines: int) -> Optional[dict]:
        """Request LLM to suggest next move"""
        prompt = f"""You are a Minesweeper game AI. Current board:

{grid_summary}

Please analyze and give the best next move (reveal or flag).
Return in JSON format:
{{"x": number, "y": number, "action": "reveal|flag", "reason": "brief reason"}}

Only return JSON, no other content."""

        try:
            if self.use_manager:
                # Call through MoRE OS LLM Manager (supports fallback chain)
                from more_core.llm.provider import LLMRequest
                request = LLMRequest(
                    prompt=prompt,
                    system="You are a professional Minesweeper game AI assistant.",
                    temperature=0.3,
                    max_tokens=100,
                )
                response = await self.llm_manager.generate(request)
                response_text = response.content.strip()
            else:
                # Direct Ollama API call (fallback)
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(
                        "http://localhost:11434/api/generate",
                        json={"model": self.model, "prompt": prompt, "stream": False},
                    )
                    r.raise_for_status()
                    data = r.json()
                    response_text = data.get("response", "").strip()

            # Extract JSON
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            return None

        return None


class MinesweeperAgent:
    """Minesweeper AI agent - integrates rule and probability reasoning"""

    def __init__(self, use_llm: bool = False, llm_model: str = None, llm_manager=None):
        self.use_llm = use_llm
        self.llm = LLMAdvisor(llm_manager=llm_manager, model=llm_model or "llama3.2:3b")
        self.reasoning = None  # Will be initialized in decide
        self.probability = None

    def set_llm_manager(self, llm_manager):
        """Inject MoRE OS LLM Manager"""
        self.llm = LLMAdvisor(llm_manager=llm_manager, model=self.llm.model)

    def decide(self, ai_view: dict) -> dict:
        """Decide next move (sync interface)"""
        # Parse input
        width = len(ai_view["visible_grid"])
        height = len(ai_view["visible_grid"][0]) if width > 0 else 0

        # Build CellInfo grid
        grid = []
        for x in range(width):
            row = []
            for y in range(height):
                cell_data = ai_view["visible_grid"][x][y]
                row.append(CellInfo(
                    x=x, y=y,
                    is_revealed=cell_data["state"] == "revealed",
                    is_flagged=cell_data["state"] == "flagged",
                    adjacent_mines=cell_data.get("adjacent_mines", 0),
                ))
            grid.append(row)

        # Initialize engine
        self.reasoning = ReasoningEngine(width, height)
        total_mines = ai_view.get("total_mines", 99)

        # Step 1: Single rule reasoning (basic 1 rule + cross analysis)
        safe_moves = self.reasoning.find_safe_moves(grid)
        if safe_moves:
            x, y = safe_moves[0]
            return {"x": x, "y": y, "action": "reveal",
                    "reason": "Rule: definitely safe"}

        mines = self.reasoning.find_mines(grid)
        if mines:
            x, y = mines[0]
            return {"x": x, "y": y, "action": "flag",
                    "reason": "Rule: definitely mine"}

        cross = self.reasoning.cross_analysis(grid)
        if cross:
            if cross["type"] == "safe":
                x, y = cross["cells"][0]
                return {"x": x, "y": y, "action": "reveal",
                        "reason": cross["reason"]}
            if cross["type"] == "mine":
                x, y = cross["cells"][0]
                return {"x": x, "y": y, "action": "flag",
                        "reason": cross["reason"]}

        # Step 2: Probability reasoning
        prob_engine = ProbabilityEngine(width, height, total_mines)
        best = prob_engine.calculate_basic_probability(grid)
        if best:
            x, y = best
            return {"x": x, "y": y, "action": "reveal",
                    "reason": "Probability: most likely safe"}

        # Step 3: LLM enhancement (if available)
        if self.use_llm and self.llm:
            import asyncio
            import concurrent.futures
            grid_summary = self._grid_to_text(ai_view["visible_grid"])
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, self.llm.suggest_move(grid_summary, total_mines)
                    )
                    llm_move = future.result(timeout=15)
                    if llm_move:
                        return llm_move
            except Exception:
                pass

        # Step 4: Random
        hidden = []
        for x in range(width):
            for y in range(height):
                if not grid[x][y].is_revealed and not grid[x][y].is_flagged:
                    hidden.append((x, y))
        if hidden:
            import random
            x, y = random.choice(hidden)
            return {"x": x, "y": y, "action": "reveal", "reason": "Random"}

        return {"x": 0, "y": 0, "action": "reveal", "reason": "No moves left"}

    def _grid_to_text(self, grid: List[List[dict]]) -> str:
        """Convert grid to text description for LLM"""
        lines = []
        for row in grid:
            row_text = []
            for cell in row:
                if cell["state"] == "revealed":
                    row_text.append(str(cell.get("adjacent_mines", ".")))
                elif cell["state"] == "flagged":
                    row_text.append("F")
                else:
                    row_text.append("#")
            lines.append(" ".join(row_text))
        return "\n".join(lines)