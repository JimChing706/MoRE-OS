"""Game state management and difficulty configuration"""

import uuid
from dataclasses import dataclass
from typing import Dict, Any, Optional
import asyncio
from datetime import datetime, timezone

from .game_engine import MinesweeperGame, GameConfig


DIFFICULTY_PRESETS = {
    "beginner": {"width": 9, "height": 9, "mines": 10},
    "intermediate": {"width": 16, "height": 16, "mines": 40},
    "expert": {"width": 30, "height": 16, "mines": 99},
    "small": {"width": 8, "height": 8, "mines": 8},
    "medium": {"width": 16, "height": 12, "mines": 32},
    "large": {"width": 24, "height": 20, "mines": 80},
    "huge": {"width": 30, "height": 24, "mines": 150},
    "custom": {"width": 0, "height": 0, "mines": 0},  # User provided
}

# Platform-specific size templates (width, height, mines) for precise scaling
_PLATFORM_TEMPLATES = {
    "desktop": {
        "small":   {"width": 8,  "height": 8,  "mines": 8},
        "medium":  {"width": 16, "height": 12, "mines": 32},
        "large":   {"width": 24, "height": 20, "mines": 80},
        "huge":    {"width": 30, "height": 24, "mines": 150},
        "expert":  {"width": 30, "height": 16, "mines": 99},
        "beginner":{"width": 9,  "height": 9,  "mines": 10},
    },
    "mobile": {
        "small":   {"width": 6,  "height": 6,  "mines": 6},
        "medium":  {"width": 12, "height": 12, "mines": 16},
        "large":   {"width": 18, "height": 18, "mines": 36},
    },
    "tablet": {
        "small":   {"width": 7,  "height": 7,  "mines": 7},
        "medium":  {"width": 14, "height": 14, "mines": 28},
        "large":   {"width": 20, "height": 20, "mines": 50},
    },
}


def create_game(difficulty: str = "beginner", custom_config: Dict[str, int] = None) -> MinesweeperGame:
    """Factory function: Create minesweeper game instance"""
    if difficulty == "custom" and custom_config:
        # Use num_mines as standard parameter name
        config_dict = custom_config.copy()
        if "mines" in config_dict:
            config_dict["num_mines"] = config_dict.pop("mines")
        config = GameConfig(**config_dict)
    elif difficulty in DIFFICULTY_PRESETS:
        cfg = DIFFICULTY_PRESETS[difficulty]
        config = GameConfig(width=cfg["width"], height=cfg["height"], num_mines=cfg["mines"])
    else:
        raise ValueError(f"Unknown difficulty: {difficulty}")
    
    return MinesweeperGame(config)


def serialize_game_state(game: MinesweeperGame) -> Dict[str, Any]:
    """Serialize game state to JSON-friendly format"""
    state = game.get_state()
    # Add AI view info (hidden mine positions)
    state["ai_view"] = {
        "visible_grid": game.get_visible_grid(),
        "revealed_count": game.cells_revealed,
        "flags_placed": game.flags_placed,
    }
    return state


def deserialize_game_state(data: Dict[str, Any]) -> MinesweeperGame:
    """Restore game instance from dictionary"""
    return MinesweeperGame.from_dict(data)


def validate_custom_config(config: Dict[str, int]) -> tuple[bool, str]:
    """Validate custom configuration"""
    width = config.get("width", 0)
    height = config.get("height", 0)
    num_mines = config.get("num_mines", config.get("mines", 0))  # Compatible with mines and num_mines
    
    if width <= 0 or height <= 0:
        return False, "Width and height must be greater than 0"
    
    if width > 100 or height > 100:
        return False, "Width and height cannot exceed 100"
    
    total_cells = width * height
    
    if num_mines <= 0:
        return False, "Number of mines must be greater than 0"
    
    if num_mines >= total_cells:
        return False, f"Mines ({num_mines}) must be less than total cells ({total_cells})"
    
    if num_mines > total_cells * 0.8:
        return False, f"Mine ratio ({num_mines/total_cells:.1%}) cannot exceed 80%"
    
    # Minimum recommended mine density: at least 5%
    if num_mines < total_cells * 0.05 and total_cells > 20:
        return False, f"Mines ({num_mines}) is too few for {total_cells} cells (recommended at least {int(total_cells*0.05)})"
    
    return True, "Configuration valid"


def get_difficulty_info(difficulty: str) -> Dict[str, Any]:
    """Get detailed difficulty information"""
    if difficulty not in DIFFICULTY_PRESETS:
        raise ValueError(f"Unknown difficulty: {difficulty}")
    
    preset = DIFFICULTY_PRESETS[difficulty]
    total_cells = preset["width"] * preset["height"]
    mine_percentage = round(preset["mines"] / total_cells * 100, 2) if total_cells > 0 else 0
    
    return {
        "name": difficulty,
        "width": preset["width"],
        "height": preset["height"],
        "mines": preset["mines"],
        "total_cells": total_cells,
        "mine_percentage": mine_percentage,
        "difficulty_level": get_difficulty_level(mine_percentage),
        "recommended_for": get_recommendation(difficulty, mine_percentage),
    }


def get_difficulty_level(percentage: float) -> str:
    """Get difficulty level based on mine density"""
    if percentage < 10:
        return "Easy"
    elif percentage < 20:
        return "Medium"
    elif percentage < 30:
        return "Hard"
    else:
        return "Expert"


def get_recommendation(difficulty: str, percentage: float) -> str:
    """Get difficulty recommendation"""
    if difficulty == "beginner":
        return "Beginner Friendly"
    elif difficulty == "small":
        return "Quick Play"
    elif difficulty == "medium":
        return "Casual Player"
    elif difficulty == "intermediate":
        return "Advanced Challenge"
    elif difficulty == "large":
        return "Seasoned Player"
    elif difficulty == "expert":
        return "Expert Level"
    elif difficulty == "huge":
        return "Extreme Challenge"
    else:
        return "Custom Config"


# —— Global Session Manager ——

class GameSessionManager:
    """Singleton session manager"""
    _instance: Optional[GameSessionManager] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._sessions: Dict[str, GameSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._initialized = True

    async def start(self):
        """Start cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_sessions())

    async def stop(self):
        """Stop cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def create_session(self, difficulty: str = "beginner",
                             custom_config: Dict[str, int] = None,
                             first_click_safe: bool = True) -> str:
        """Create new game session"""
        game = create_game(difficulty, custom_config)
        game_id = str(uuid.uuid4())[:8]

        async with self._lock:
            session = GameSession(game_id, game)
            self._sessions[game_id] = session

        return game_id

    async def get_session(self, game_id: str) -> Optional[GameSession]:
        """Get session"""
        async with self._lock:
            return self._sessions.get(game_id)

    async def remove_session(self, game_id: str):
        """Remove session"""
        async with self._lock:
            self._sessions.pop(game_id, None)

    async def list_sessions(self) -> Dict[str, Any]:
        """List all active sessions"""
        async with self._lock:
            return {
                "count": len(self._sessions),
                "sessions": [
                    {
                        "id": s.game_id,
                        "created_at": s.created_at.isoformat(),
                        "move_count": s.move_count,
                        "result": s.game.result.value,
                    }
                    for s in self._sessions.values()
                ]
            }

    async def _cleanup_stale_sessions(self):
        """Periodically cleanup sessions inactive for over 1 hour"""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            cutoff = datetime.now(timezone.utc).timestamp() - 3600
            async with self._lock:
                to_remove = [
                    sid for sid, s in self._sessions.items()
                    if s.last_move_at.timestamp() < cutoff
                ]
                for sid in to_remove:
                    self._sessions.pop(sid, None)


# —— Helper Classes ——

class GameSession:
    """Manage single minesweeper game session"""

    def __init__(self, game_id: str, game: MinesweeperGame):
        self.game_id = game_id
        self.game = game
        self.created_at = datetime.now(timezone.utc)
        self.last_move_at = datetime.now(timezone.utc)
        self.move_count = 0
        self._lock = asyncio.Lock()

    async def execute_move(self, x: int, y: int, action: str) -> Dict[str, Any]:
        """Execute a move (thread safe)"""
        async with self._lock:
            if action == "reveal":
                state = self.game.reveal(x, y)
            elif action == "flag":
                state = self.game.toggle_flag(x, y)
            elif action == "chord":
                state = self.game.chord(x, y)
            else:
                raise ValueError(f"Unknown action: {action}")

            self.last_move_at = datetime.now(timezone.utc)
            self.move_count += 1

            # Publish event when game ends
            if self.game.is_game_over():
                await self._publish_game_completed()

            return state

    async def _publish_game_completed(self) -> None:
        """Publish game completed event (for DGM collection)"""
        # Event propagates through MoRE OS event bus
        # Specific data supplemented in task system callback
        pass

    async def get_state(self) -> Dict[str, Any]:
        """Get current state"""
        async with self._lock:
            return serialize_game_state(self.game)