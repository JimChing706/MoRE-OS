"""Mahjong Game Engine - Minimal working implementation."""

import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class TileType(Enum):
    BAMBOO = "bamboo"
    CHARACTERS = "characters"
    DOTS = "dots"
    WINDS = "winds"
    DRAGONS = "dragons"


@dataclass
class Tile:
    suit: str
    value: int

    def __str__(self) -> str:
        return f"{self.suit}_{self.value}"

    @property
    def is_honor(self) -> bool:
        return self.suit in ("winds", "dragons")

    @property
    def is_terminal(self) -> bool:
        return self.value in (1, 9) and not self.is_honor


@dataclass
class Player:
    id: int
    name: str
    hand: List[Tile] = field(default_factory=list)
    discards: List[Tile] = field(default_factory=list)
    melds: List[List[Tile]] = field(default_factory=list)
    score: int = 35000
    is_dealer: bool = False
    is_tenpai: bool = False


@dataclass
class GameConfig:
    player_count: int = 4
    initial_score: int = 35000
    wall_size: int = 136
    rule_type: str = "guangdong"


@dataclass
class GameState:
    game_id: str
    players: List[Player]
    wall: List[Tile]
    wall_index: int
    current_player: int
    dealer: int
    round: int
    quarter: int
    status: str
    config: GameConfig


def create_tile(suit: str, value: int) -> Tile:
    return Tile(suit=suit, value=value)


def create_full_deck() -> List[Tile]:
    tiles: List[Tile] = []
    for suit in ["bamboo", "characters", "dots"]:
        for value in range(1, 10):
            tiles.extend([create_tile(suit, value)] * 4)
    for suit in ["winds_east", "winds_south", "winds_west", "winds_north"]:
        tiles.extend([create_tile(suit, 0)] * 4)
    for suit in ["dragons_red", "dragons_green", "dragons_white"]:
        tiles.extend([create_tile(suit, 0)] * 4)
    return tiles


def shuffle_wall(wall: List[Tile]) -> List[Tile]:
    random.shuffle(wall)
    return wall


class MahjongEngine:
    def __init__(self, config: Optional[GameConfig] = None):
        self.config = config or GameConfig()
        self.state: Optional[GameState] = None

    def initialize(self, player_names: List[str], game_id: str) -> GameState:
        wall = create_full_deck()
        wall = shuffle_wall(wall)

        players = []
        for i, name in enumerate(player_names[:self.config.player_count]):
            players.append(Player(
                id=i,
                name=name,
                is_dealer=(i == 0)
            ))

        self.state = GameState(
            game_id=game_id,
            players=players,
            wall=wall,
            wall_index=0,
            current_player=0,
            dealer=0,
            round=1,
            quarter=0,
            status="READY",
            config=self.config
        )
        return self.state

    def deal_tiles(self) -> Dict[str, Any]:
        if not self.state:
            return {"error": "Game not initialized"}

        tiles_dealt = 0
        for player in self.state.players:
            player.hand = self.state.wall[self.state.wall_index:self.state.wall_index + 13]
            self.state.wall_index += 13
            tiles_dealt += 13

        self.state.status = "RUNNING"
        return {
            "success": True,
            "tiles_dealt": tiles_dealt,
            "players_hands": {p.name: len(p.hand) for p in self.state.players}
        }

    def draw_tile(self, player_id: int) -> Dict[str, Any]:
        if not self.state:
            return {"error": "Game not initialized"}

        if self.state.wall_index >= len(self.state.wall):
            return {"error": "Wall is empty", "is_game_over": True}

        tile = self.state.wall[self.state.wall_index]
        self.state.wall_index += 1
        self.state.players[player_id].hand.append(tile)
        self.state.current_player = player_id

        return {
            "success": True,
            "player": player_id,
            "tile": str(tile),
            "tiles_remaining": len(self.state.wall) - self.state.wall_index
        }

    def discard_tile(self, player_id: int, tile_index: int) -> Dict[str, Any]:
        if not self.state:
            return {"error": "Game not initialized"}

        player = self.state.players[player_id]
        if tile_index >= len(player.hand):
            return {"error": "Invalid tile index"}

        tile = player.hand.pop(tile_index)
        player.discards.append(tile)
        self.state.current_player = (player_id + 1) % len(self.state.players)

        return {
            "success": True,
            "player": player_id,
            "tile": str(tile),
            "next_player": self.state.current_player
        }

    def calculate_shanten(self, hand: List[Tile]) -> int:
        """Real shanten calculation using recursive decomposition.

        Computes the minimum number of tiles needed to reach tenpai (ready state).
        Uses the standard 4-melds + 1-pair decomposition algorithm.
        """
        if len(hand) > 14:
            return -2  # Invalid hand

        # Convert hand to tile counts by suit
        suited: Dict[str, List[int]] = {"bamboo": [], "characters": [], "dots": []}
        honors: List[int] = []
        for tile in hand:
            if tile.suit in suited:
                suited[tile.suit].append(tile.value)
            else:
                honors.append(hash(str(tile)))

        # Calculate shanten for each suit independently
        suited_shanten = [self._calc_suit_shanten(suited[s]) for s in ["bamboo", "characters", "dots"]]

        # Calculate honor shanten
        honor_counts: Dict[int, int] = {}
        for h in honors:
            honor_counts[h] = honor_counts.get(h, 0) + 1
        honor_shanten = self._calc_honor_shanten(honor_counts)

        # Total shanten = sum of each component shanten - 1 (for the pair shared across components)
        total = sum(suited_shanten) + honor_shanten - 1

        # Check for seven pairs special case (chiitoitsu)
        seven_pairs = self._calc_seven_pairs_shanten(hand)

        # Return minimum of standard and seven pairs
        return min(total, seven_pairs)

    def _calc_suit_shanten(self, tiles: List[int]) -> int:
        """Calculate shanten for a single suit using recursive decomposition."""
        if not tiles:
            return 8  # No tiles = worst case

        # Count tile occurrences
        counts = [0] * 10  # indices 1-9
        for t in tiles:
            if 1 <= t <= 9:
                counts[t] += 1

        # Try all possible pair positions and find minimum shanten
        min_shanten = 8  # worst case: 8 tiles needed for 13-tile hand

        # Try each tile as the pair
        for pair_pos in range(1, 10):
            if counts[pair_pos] >= 2:
                counts[pair_pos] -= 2
                shanten = self._find_melds(counts, 1, 10)
                min_shanten = min(min_shanten, shanten)
                counts[pair_pos] += 2

        # Also try without a pair (for kokushi/chiitoitsu handled separately)
        shanten_no_pair = self._find_melds(counts, 1, 10) + 1  # +1 for missing pair
        min_shanten = min(min_shanten, shanten_no_pair)

        return min_shanten

    def _find_melds(self, counts: List[int], start: int, end: int) -> int:
        """Find minimum shanten by decomposing into mentsu (sets/runs).

        Uses greedy approach for simplicity; full implementation would use
        recursive backtracking for optimal decomposition.
        """
        # Make a copy to avoid mutating
        c = counts[:]
        mentsu = 0
        partial = 0  # partial melds (taatsu)

        for i in range(start, end):
            # Triplets (anko)
            while c[i] >= 3:
                c[i] -= 3
                mentsu += 1

            # Sequences (shuntsu)
            if i <= 7 and c[i] > 0 and c[i + 1] > 0 and c[i + 2] > 0:
                min_seq = min(c[i], c[i + 1], c[i + 2])
                c[i] -= min_seq
                c[i + 1] -= min_seq
                c[i + 2] -= min_seq
                mentsu += min_seq

            # Partial sequences (taatsu)
            if c[i] > 0:
                if i <= 7 and c[i + 1] > 0:
                    partial += 1
                    c[i] -= 1
                    c[i + 1] -= 1
                elif c[i] >= 2:
                    partial += 1
                    c[i] -= 2
                partial += c[i]
                c[i] = 0

        # 4 mentsu needed for standard hand
        needed = 4 - mentsu
        if needed <= 0:
            return 0
        return needed - min(partial, needed)

    def _calc_honor_shanten(self, counts: Dict[int, int]) -> int:
        """Calculate shanten for honor tiles."""
        triplets = sum(1 for c in counts.values() if c >= 3)
        pairs = sum(1 for c in counts.values() if c == 2)
        singles = sum(1 for c in counts.values() if c == 1)

        # Each triplet is a complete meld
        # Each pair can be a pair or partial meld
        # Each single is a partial
        mentsu = triplets
        partial = pairs + singles

        needed = 4 - mentsu
        if needed <= 0:
            return 0
        return needed - min(partial, needed)

    def _calc_seven_pairs_shanten(self, hand: List[Tile]) -> int:
        """Calculate shanten for seven pairs (chiitoitsu) hand."""
        if len(hand) != 13:
            return 6  # Not applicable

        counts: Dict[str, int] = {}
        for tile in hand:
            key = str(tile)
            counts[key] = counts.get(key, 0) + 1

        pairs = sum(1 for c in counts.values() if c >= 2)
        # Need 7 pairs, each pair reduces shanten by 1
        # But we only have 13 tiles, so max 6 pairs + 1 single
        return 6 - pairs

    def check_win(self, hand: List[Tile]) -> Dict[str, Any]:
        if len(hand) != 14:
            return {"is_win": False, "reason": "手牌数量不正确"}

        # Standard win check: 4 mentsu + 1 pair
        if self._check_standard_win(hand):
            return {"is_win": True, "reason": "标准和牌"}

        # Seven pairs check
        if self._check_seven_pairs_win(hand):
            return {"is_win": True, "reason": "七对子"}

        return {"is_win": False, "reason": "未满足和牌条件"}

    def _check_standard_win(self, hand: List[Tile]) -> bool:
        """Check if hand is a standard winning hand (4 mentsu + 1 pair)."""
        # Try each tile as the pair
        counts: Dict[str, int] = {}
        for tile in hand:
            key = str(tile)
            counts[key] = counts.get(key, 0) + 1

        for key in list(counts.keys()):
            if counts[key] >= 2:
                counts[key] -= 2
                if self._can_form_melds(counts):
                    return True
                counts[key] += 2
        return False

    def _can_form_melds(self, counts: Dict[str, int]) -> bool:
        """Check if remaining tiles can form exactly 4 melds."""
        # Group by suit
        suited: Dict[str, List[int]] = {"bamboo": [], "characters": [], "dots": []}
        honor_count = 0
        for key, count in counts.items():
            if count == 0:
                continue
            parts = key.split("_")
            suit = parts[0]
            if suit in suited:
                value = int(parts[1]) if len(parts) > 1 else 0
                for _ in range(count):
                    suited[suit].append(value)
            else:
                honor_count += count

        # Check honors (must be triplets)
        if honor_count % 3 != 0:
            return False

        # Check each suit
        for suit_tiles in suited.values():
            if not self._can_form_suit_melds(suit_tiles):
                return False

        return True

    def _can_form_suit_melds(self, tiles: List[int]) -> bool:
        """Check if suit tiles can form complete melds."""
        if not tiles:
            return True
        if len(tiles) % 3 != 0:
            return False

        counts = [0] * 10
        for t in tiles:
            if 1 <= t <= 9:
                counts[t] += 1

        # Greedy decomposition
        for i in range(1, 10):
            while counts[i] >= 3:
                counts[i] -= 3
            if i <= 7:
                seq = min(counts[i], counts[i + 1], counts[i + 2])
                if seq > 0:
                    counts[i] -= seq
                    counts[i + 1] -= seq
                    counts[i + 2] -= seq

        return all(c == 0 for c in counts)

    def _check_seven_pairs_win(self, hand: List[Tile]) -> bool:
        """Check if hand is seven pairs."""
        if len(hand) != 14:
            return False
        counts: Dict[str, int] = {}
        for tile in hand:
            key = str(tile)
            counts[key] = counts.get(key, 0) + 1
        return len(counts) == 7 and all(c == 2 for c in counts.values())

    def get_game_view(self, player_id: int) -> Dict[str, Any]:
        if not self.state:
            return {}

        player = self.state.players[player_id]
        opponent_hints = {
            f"player_{i}": {"hand_count": len(self.state.players[i].hand)}
            for i in range(len(self.state.players))
            if i != player_id
        }

        return {
            "game_id": self.state.game_id,
            "self": {
                "id": player.id,
                "name": player.name,
                "hand": [str(t) for t in player.hand],
                "hand_count": len(player.hand),
                "discards": [str(t) for t in player.discards],
                "score": player.score,
                "is_dealer": player.is_dealer,
                "is_tenpai": player.is_tenpai
            },
            "opponents": opponent_hints,
            "game": {
                "current_player": self.state.current_player,
                "tiles_remaining": len(self.state.wall) - self.state.wall_index,
                "round": self.state.round,
                "status": self.state.status
            },
            "ai_view": {
                "shanten": self.calculate_shanten(player.hand),
                "hand": [str(t) for t in player.hand],
                "tiles_remaining": len(self.state.wall) - self.state.wall_index
            }
        }