"""Three-stream memory store: episodic / semantic / procedural.

In-process baseline uses bounded lists; Redis-backed adapter can be
substituted without touching callers (same interface).

v0.8.1 — per-request tracking fields (task_id, layer, ttl) added for
cross-request observability and lifecycle management.
"""

from __future__ import annotations

import builtins
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum


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

    # Per-request tracking — enables cross-request observability
    task_id: str = ""
    layer: str = ""  # e.g. "L0", "L4"
    ttl: float | None = None  # absolute expiry timestamp (None = never)


class MemoryStore:
    def __init__(self, capacity: int = 2048) -> None:
        self._capacity = capacity
        self._streams: dict[MemoryKind, deque[MemoryEntry]] = defaultdict(
            lambda: deque(maxlen=capacity)
        )

    def put(self, entry: MemoryEntry) -> None:
        """Store a memory entry in its stream.

        Entries with an expired TTL are silently dropped.
        """
        if entry.ttl is not None and time.time() > entry.ttl:
            return
        self._streams[entry.kind].append(entry)

    def list(self, kind: MemoryKind | None = None, limit: int = 0) -> list[MemoryEntry]:
        """List entries, optionally filtered by kind (TTL-aware).

        Args:
            kind: Optional kind filter.
            limit: Max entries to return; 0 or negative means no limit.
        """
        now = time.time()
        entries = (
            [e for stream in self._streams.values() for e in stream]
            if kind is None
            else list(self._streams[kind])
        )
        entries = [e for e in entries if e.ttl is None or now <= e.ttl]
        if limit and limit > 0:
            return entries[:limit]
        return entries

    def search(
        self,
        query: str,
        kind: MemoryKind | None = None,
        top_k: int = 5,
        *,
        task_id: str = "",
    ) -> builtins.list[MemoryEntry]:
        """Full-text search across memory, with optional task_id filter."""
        q = unicodedata.normalize("NFKC", query).casefold()
        candidates = self.list(kind)
        if task_id:
            candidates = [e for e in candidates if e.task_id == task_id]
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

    def by_task(self, task_id: str) -> builtins.list[MemoryEntry]:
        """Return all memory entries for a given *task_id* (cross-request trace)."""
        results: list[MemoryEntry] = []
        for stream in self._streams.values():
            for e in stream:
                if e.task_id == task_id:
                    results.append(e)
        return results

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count of evicted items."""
        now = time.time()
        removed = 0
        for stream in self._streams.values():
            before = len(stream)
            # Rebuild deque without expired entries
            kept = deque(
                (e for e in stream if e.ttl is None or now <= e.ttl),
                maxlen=stream.maxlen,
            )
            removed += before - len(kept)
            stream.clear()
            stream.extend(kept)
        return removed

    def stats(self) -> dict[str, int]:
        return {k.value: len(v) for k, v in self._streams.items()}
