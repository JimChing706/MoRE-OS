"""SQLite-backed persistent memory store.

Drop-in replacement for the in-memory :class:`MemoryStore`.  Keeps the
same public interface so callers need not change.

Usage::

    store = SQLiteMemoryStore("data/memory.db")
    store.put(MemoryEntry(content="hello"))
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .store import MemoryEntry, MemoryKind, MemoryStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'episodic',
    content     TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '[]',
    score       REAL NOT NULL DEFAULT 0.0,
    created_at  REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
"""


class SQLiteMemoryStore(MemoryStore):
    """Persistent three-stream memory backed by SQLite."""

    def __init__(self, db_path: str | Path, capacity: int = 2048) -> None:
        super().__init__(capacity)
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def put(self, entry: MemoryEntry) -> None:
        super().put(entry)
        # Store NFKC-normalised content so LOWER() LIKE matches the
        # casefolded + NFKC-normalised query in search().
        import unicodedata
        normalized = unicodedata.normalize("NFKC", entry.content)
        self._conn.execute(
            "INSERT OR REPLACE INTO memories (id, kind, content, tags, score, created_at, access_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.kind.value,
                normalized,
                json.dumps(entry.tags),
                entry.score,
                entry.created_at,
                entry.access_count,
            ),
        )
        self._conn.commit()

    def search(self, query: str, kind: MemoryKind | None = None, top_k: int = 5) -> list[MemoryEntry]:
        import unicodedata
        q = unicodedata.normalize("NFKC", query).casefold()
        sql = "SELECT id, kind, content, tags, score, created_at, access_count FROM memories"
        params: list = []
        clauses: list[str] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY (CASE WHEN LOWER(content) LIKE ? THEN 1 ELSE 0 END) DESC, score DESC, access_count DESC"
        params.append(f"%{q}%")
        sql += " LIMIT ?"
        params.append(top_k)
        rows = self._conn.execute(sql, params).fetchall()
        results: list[MemoryEntry] = []
        ids: list[str] = []
        for row in rows:
            entry = MemoryEntry(
                id=row[0],
                kind=MemoryKind(row[1]),
                content=row[2],
                tags=json.loads(row[3]),
                score=row[4],
                created_at=row[5],
                access_count=row[6] + 1,
            )
            ids.append(entry.id)
            results.append(entry)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"UPDATE memories SET access_count = access_count + 1 WHERE id IN ({placeholders})",
                ids,
            )
            self._conn.commit()
        return results

    def list(self, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        sql = "SELECT id, kind, content, tags, score, created_at, access_count FROM memories"
        params: list = []
        if kind is not None:
            sql += " WHERE kind = ?"
            params.append(kind.value)
        sql += " ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            MemoryEntry(
                id=r[0], kind=MemoryKind(r[1]), content=r[2],
                tags=json.loads(r[3]), score=r[4], created_at=r[5], access_count=r[6],
            )
            for r in rows
        ]

    def stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) FROM memories GROUP BY kind"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def close(self) -> None:
        self._conn.close()
