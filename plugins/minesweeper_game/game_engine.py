"""Minesweeper game core engine - complete game logic implementation"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pydantic


class CellState(Enum):
    """Cell state enumeration"""
    HIDDEN = "hidden"       # Not revealed
    REVEALED = "revealed"   # Already revealed
    FLAGGED = "flagged"     # Flagged as mine
    QUESTION = "question"  # Marked with question


@dataclass
class Cell:
    """Minesweeper cell"""
    x: int
    y: int
    is_mine: bool = False
    adjacent_mines: int = 0
    state: CellState = CellState.HIDDEN


class GameDifficulty(Enum):
    """Game difficulty configuration"""
    BEGINNER = {"width": 9, "height": 9, "mines": 10}
    INTERMEDIATE = {"width": 16, "height": 16, "mines": 40}
    EXPERT = {"width": 30, "height": 16, "mines": 99}
    CUSTOM = {"width": 0, "height": 0, "mines": 0}


@dataclass
class GameConfig:
    """Game configuration"""
    width: int
    height: int
    num_mines: int
    first_click_safe: bool = True  # First click won't hit mine


class GameResult(Enum):
    """Game result"""
    ONGOING = "ongoing"
    WON = "won"
    LOST = "lost"


@dataclass
class GameState:
    """Complete game state (serializable)"""
    config: dict[str, Any]
    cells: list[list[dict[str, Any]]]
    flags_placed: int
    cells_revealed: int
    result: str
    elapsed_seconds: float
    move_count: int = 0

    @classmethod
    def from_game(cls, game: "MinesweeperGame") -> "GameState":
        """Build state object from game instance"""
        cells = []
        for row in game.grid:
            cell_row = []
            for cell in row:
                cell_row.append({
                    "x": cell.x,
                    "y": cell.y,
                    "is_mine": cell.is_mine,
                    "adjacent_mines": cell.adjacent_mines,
                    "state": cell.state.value,
                })
            cells.append(cell_row)

        return cls(
            config=game.config.__dict__.copy(),
            cells=cells,
            flags_placed=game.flags_placed,
            cells_revealed=game.cells_revealed,
            result=game.result.value,
            elapsed_seconds=game.elapsed_seconds,
            move_count=game.move_count,
        )


def import_time():
    """Time function to avoid circular imports"""
    import time
    return time.time()


class MinesweeperGame:
    """Minesweeper game core engine - logic only layer"""

    DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def __init__(self, config: GameConfig, first_click_safe: bool = True):
        self.config = config
        self.first_click_safe = first_click_safe
        self._create_grid()
        self.flags_placed = 0
        self.cells_revealed = 0
        self.result = GameResult.ONGOING
        self.start_time = None
        self.elapsed_seconds = 0.0
        self.move_count = 0
        self._first_click = True
        self._initialized = False

    def _create_grid(self) -> None:
        """Create empty grid"""
        self.grid = [
            [Cell(x, y) for y in range(self.config.height)]
            for x in range(self.config.width)
        ]

    def _place_mines(self, safe_x: int, safe_y: int) -> None:
        """Randomly place mines (avoiding first click safe zone)"""
        safe_zone = set()
        if self.first_click_safe:
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    nx, ny = safe_x + dx, safe_y + dy
                    if 0 <= nx < self.config.width and 0 <= ny < self.config.height:
                        safe_zone.add((nx, ny))

        positions = [(x, y) for x in range(self.config.width)
                     for y in range(self.config.height)
                     if (x, y) not in safe_zone]

        mines_placed = 0
        while mines_placed < self.config.num_mines:
            if not positions:
                break
            idx = random.randrange(len(positions))
            x, y = positions.pop(idx)
            self.grid[x][y].is_mine = True
            mines_placed += 1

        self._calculate_adjacent_counts()

    def _calculate_adjacent_counts(self) -> None:
        """Calculate number of mines around each cell"""
        for x in range(self.config.width):
            for y in range(self.config.height):
                if not self.grid[x][y].is_mine:
                    count = sum(
                        1 for dx, dy in self.DIRECTIONS
                        if 0 <= x + dx < self.config.width
                        and 0 <= y + dy < self.config.height
                        and self.grid[x + dx][y + dy].is_mine
                    )
                    self.grid[x][y].adjacent_mines = count

    def _reveal_cell(self, x: int, y: int) -> GameResult:
        """Recursively reveal cells"""
        if not (0 <= x < self.config.width and 0 <= y < self.config.height):
            return GameResult.ONGOING

        cell = self.grid[x][y]

        if cell.state != CellState.HIDDEN:
            return GameResult.ONGOING

        if cell.is_mine:
            self.result = GameResult.LOST
            return GameResult.LOST

        cell.state = CellState.REVEALED
        self.cells_revealed += 1

        if cell.adjacent_mines == 0:
            for dx, dy in self.DIRECTIONS:
                self._reveal_cell(x + dx, y + dy)

        return self._check_win()

    def _check_win(self) -> GameResult:
        """Check if player has won"""
        total_cells = self.config.width * self.config.height
        non_mine_cells = total_cells - self.config.num_mines

        if self.cells_revealed >= non_mine_cells:
            self.result = GameResult.WON
            return GameResult.WON

        return GameResult.ONGOING

    def reveal(self, x: int, y: int) -> dict[str, Any]:
        """Execute reveal operation"""
        if self.result != GameResult.ONGOING:
            return self.get_state()

        if self._first_click:
            self.start_time = self.start_time or import_time()
            self._place_mines(x, y)
            self._first_click = False
            self._initialized = True

        self.move_count += 1
        self._reveal_cell(x, y)

        if self.result == GameResult.LOST:
            self._reveal_all_mines()

        return self.get_state()

    def toggle_flag(self, x: int, y: int) -> dict[str, Any]:
        """Toggle flag state"""
        if self.result != GameResult.ONGOING:
            return self.get_state()

        cell = self.grid[x][y]
        if cell.state == CellState.HIDDEN:
            cell.state = CellState.FLAGGED
            self.flags_placed += 1
        elif cell.state == CellState.FLAGGED:
            cell.state = CellState.HIDDEN
            self.flags_placed -= 1

        self.move_count += 1
        return self.get_state()

    def chord(self, x: int, y: int) -> dict[str, Any]:
        """Double-click / number key quick reveal: auto-reveal neighbors when flag count equals number"""
        if self.result != GameResult.ONGOING:
            return self.get_state()

        cell = self.grid[x][y]
        # Can only operate on revealed number cells
        if cell.state != CellState.REVEALED or cell.is_mine or cell.adjacent_mines == 0:
            return self.get_state()

        # Count surrounding flags
        flag_count = 0
        hidden_neighbors = []
        for dx, dy in self.DIRECTIONS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.config.width and 0 <= ny < self.config.height:
                neighbor = self.grid[nx][ny]
                if neighbor.state == CellState.FLAGGED:
                    flag_count += 1
                elif neighbor.state == CellState.HIDDEN:
                    hidden_neighbors.append((nx, ny))

        # Only auto-reveal when flag count equals number
        if flag_count == cell.adjacent_mines:
            self.move_count += 1
            # Reveal all unflagged hidden neighbors
            for nx, ny in hidden_neighbors:
                self._reveal_cell(nx, ny)
                if self.result == GameResult.LOST:
                    self._reveal_all_mines()
                    break

        return self.get_state()

    def _reveal_all_mines(self) -> None:
        """Show all mines when game ends"""
        for row in self.grid:
            for cell in row:
                if cell.is_mine and cell.state == CellState.HIDDEN:
                    cell.state = CellState.REVEALED

    def get_state(self) -> dict[str, Any]:
        """Get current game state as dictionary"""
        return GameState.from_game(self).__dict__

    def is_game_over(self) -> bool:
        """Check if game is over"""
        return self.result != GameResult.ONGOING

    def get_visible_grid(self) -> list[list[dict[str, Any]]]:
        """Get player-visible grid (with info hidden)"""
        visible = []
        for row in self.grid:
            vis_row = []
            for cell in row:
                if cell.state == CellState.REVEALED:
                    vis_row.append({
                        "x": cell.x,
                        "y": cell.y,
                        "adjacent_mines": cell.adjacent_mines,
                        "state": "revealed",
                    })
                elif cell.state == CellState.FLAGGED:
                    vis_row.append({"x": cell.x, "y": cell.y, "state": "flagged"})
                else:
                    vis_row.append({"x": cell.x, "y": cell.y, "state": "hidden"})
            visible.append(vis_row)
        return visible

    def to_dict(self) -> dict[str, Any]:
        """Full serialization (including mine distribution)"""
        return self.get_state()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MinesweeperGame":
        """Restore game instance from dictionary"""
        config = GameConfig(**data["config"])
        game = cls(config)
        game.grid = [
            [Cell(**cell_data) for cell_data in row]
            for row in data["cells"]
        ]
        game.flags_placed = data["flags_placed"]
        game.cells_revealed = data["cells_revealed"]
        game.result = GameResult(data["result"])
        game.elapsed_seconds = data["elapsed_seconds"]
        game.move_count = data["move_count"]
        game._initialized = True
        return game