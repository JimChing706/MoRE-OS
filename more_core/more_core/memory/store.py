"""Three-stream memory store: episodic / semantic / procedural.

In-process baseline uses bounded lists; Redis-backed adapter can be
substituted without touching callers (same interface).
"""

from __future__ import annotations

import time
import unicodedata
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass(slots=True)
class MemoryEntry:
    id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:10]}")
    kind: MemoryKind = MemoryKind.EPISODIC
    content: str = ""
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    created_at: float = field(default_factory=time.time)
    access_count: int = 0


class MemoryStore:
    def __init__(self, capacity: int = 2048) -> None:
        self._capacity = capacity
        self._streams: dict[MemoryKind, Deque[MemoryEntry]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def put(self, entry: MemoryEntry) -> None:
        self._streams[entry.kind].append(entry)

    def list(self, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        if kind is None:
            return [e for stream in self._streams.values() for e in stream]
        return list(self._streams[kind])

    def search(self, query: str, kind: MemoryKind | None = None, top_k: int = 5) -> list[MemoryEntry]:
        # NFKC normalize + casefold for CJK fullwidth/halfwidth parity
        q = unicodedata.normalize("NFKC", query).casefold()
        candidates = self.list(kind)
        ranked = sorted(
            candidates,
            key=lambda e: (
                q in unicodedata.normalize("NFKC", e.content).casefold(),
                e.score,
                e.access_count,
            ),
            reverse=True,
        )
        for e in ranked[:top_k]:
            e.access_count += 1
        return ranked[:top_k]

    def stats(self) -> dict[str, int]:
        return {k.value: len(v) for k, v in self._streams.items()}
