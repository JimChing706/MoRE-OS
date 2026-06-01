"""SQLite-backed evolution archive.

Drop-in replacement for the in-memory :class:`EvolutionArchive`.
Persists all agent variants across restarts.

Usage::

    archive = SQLiteEvolutionArchive("data/evolution.db")
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .archive import EvolutionArchive, EvolvedAgent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,
    generation  INTEGER NOT NULL DEFAULT 0,
    branch      TEXT NOT NULL DEFAULT 'main',
    code        TEXT NOT NULL DEFAULT '',
    performance REAL NOT NULL DEFAULT 0.0,
    description TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    verified    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_agents_branch ON agents(branch);
CREATE INDEX IF NOT EXISTS idx_agents_perf ON agents(performance DESC);
"""


class SQLiteEvolutionArchive(EvolutionArchive):
    """Persistent evolution archive backed by SQLite."""

    def __init__(self, db_path: str | Path, max_size: int = 500) -> None:
        super().__init__(max_size)
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Hydrate in-memory indices from persisted data."""
        rows = self._conn.execute(
            "SELECT id, parent_id, generation, branch, code, performance, "
            "description, created_at, verified FROM agents"
        ).fetchall()
        for r in rows:
            agent = EvolvedAgent(
                id=r[0], parent_id=r[1], generation=r[2], branch=r[3],
                code=r[4], performance=r[5], description=r[6],
                created_at=r[7], verified=bool(r[8]),
            )
            self._agents[agent.id] = agent
            self._by_branch.setdefault(agent.branch, []).append(agent.id)

    def add(self, agent: EvolvedAgent) -> None:
        super().add(agent)
        self._conn.execute(
            "INSERT OR REPLACE INTO agents "
            "(id, parent_id, generation, branch, code, performance, description, created_at, verified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent.id, agent.parent_id, agent.generation, agent.branch,
                agent.code, agent.performance, agent.description,
                agent.created_at, int(agent.verified),
            ),
        )
        self._conn.commit()

    def update(self, agent: EvolvedAgent) -> None:
        """Persist in-place mutations (e.g. performance, verified) back to DB."""
        self._agents[agent.id] = agent
        self._conn.execute(
            "UPDATE agents SET performance=?, verified=?, description=? WHERE id=?",
            (agent.performance, int(agent.verified), agent.description, agent.id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
