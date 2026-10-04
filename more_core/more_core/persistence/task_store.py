"""SQLite-backed persistent task store.

Drop-in replacement for the module-level ``_task_store`` dict in
``api/routers/tasks.py``.  Keeps the same data shape so callers need
minimal change.

Usage::

    store = SQLiteTaskStore("data/tasks.db")
    store.create_task("task-1", {"title": "Hello", "status": "pending"})
    task = store.get_task("task-1")
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    type         TEXT NOT NULL DEFAULT 'nlp_task',
    plugin_type  TEXT,
    query        TEXT NOT NULL DEFAULT '',
    context      TEXT NOT NULL DEFAULT '{}',
    title        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending',
    progress     INTEGER NOT NULL DEFAULT 0,
    current_step TEXT,
    artifacts    TEXT NOT NULL DEFAULT '[]',
    warnings     TEXT NOT NULL DEFAULT '[]',
    result       TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT,
    parent_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
"""


class SQLiteTaskStore:
    """Persistent task store backed by SQLite.

    Mirrors the in-memory dict interface used by ``api/routers/tasks.py``.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def _migrate(self) -> None:
        """为既有部署补齐列（幂等）。"""
        cols = {str(r["name"]) for r in self._conn.execute("PRAGMA table_info(tasks)")}
        if "parent_id" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN parent_id TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id)"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API (mirrors dict interface)
    # ------------------------------------------------------------------

    def create_task(self, task_id: str, info: dict[str, Any]) -> None:
        """Insert a new task record."""
        ctx = info.get("context", {}) or {}
        context_json = json.dumps(ctx)
        artifacts_json = json.dumps(info.get("artifacts", []))
        warnings_json = json.dumps(info.get("warnings", []))
        parent_id = info.get("parent_id") or (ctx.get("parent_id") if isinstance(ctx, dict) else None)
        self._conn.execute(
            """INSERT OR REPLACE INTO tasks
               (task_id, type, plugin_type, query, context, title,
                description, status, progress, current_step,
                artifacts, warnings, result, error,
                created_at, started_at, completed_at, parent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                info.get("type", "nlp_task"),
                info.get("plugin_type"),
                info.get("query", info.get("description", info.get("title", ""))),
                context_json,
                info.get("title", ""),
                info.get("description", ""),
                info.get("status", "pending"),
                info.get("progress", 0),
                info.get("current_step"),
                artifacts_json,
                warnings_json,
                info.get("result"),
                info.get("error"),
                info.get("created_at", ""),
                info.get("started_at"),
                info.get("completed_at"),
                parent_id,
            ),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve a single task by id, or None."""
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def update_task(self, task_id: str, updates: dict[str, Any]) -> None:
        """Update fields of an existing task."""
        existing = self.get_task(task_id)
        if existing is None:
            return
        merged = {**existing, **updates}
        if "context" in updates and isinstance(updates["context"], dict):
            merged["context"] = json.dumps(updates["context"])
        elif isinstance(merged.get("context"), dict):
            merged["context"] = json.dumps(merged["context"])
        if "artifacts" in updates and isinstance(updates["artifacts"], list):
            merged["artifacts"] = json.dumps(updates["artifacts"])
        elif isinstance(merged.get("artifacts"), list):
            merged["artifacts"] = json.dumps(merged["artifacts"])
        if "warnings" in updates and isinstance(updates["warnings"], list):
            merged["warnings"] = json.dumps(updates["warnings"])
        elif isinstance(merged.get("warnings"), list):
            merged["warnings"] = json.dumps(merged["warnings"])
        self._conn.execute(
            """UPDATE tasks SET
                 type=?, plugin_type=?, query=?, context=?, title=?,
                 description=?, status=?, progress=?, current_step=?,
                 artifacts=?, warnings=?, result=?, error=?,
                 created_at=?, started_at=?, completed_at=?
               WHERE task_id=?""",
            (
                merged.get("type", "nlp_task"),
                merged.get("plugin_type"),
                merged.get("query", ""),
                merged.get("context", "{}"),
                merged.get("title", ""),
                merged.get("description", ""),
                merged.get("status", "pending"),
                merged.get("progress", 0),
                merged.get("current_step"),
                merged.get("artifacts", "[]"),
                merged.get("warnings", "[]"),
                merged.get("result"),
                merged.get("error"),
                merged.get("created_at", ""),
                merged.get("started_at"),
                merged.get("completed_at"),
                task_id,
            ),
        )
        self._conn.commit()

    def list_children(self, parent_id: str) -> list[dict[str, Any]]:
        """返回某父任务下的全部子任务（按 task_id 升序，即 REQ 编号顺序）。"""
        cur = self._conn.execute(
            "SELECT * FROM tasks WHERE parent_id = ? ORDER BY task_id ASC", (parent_id,)
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List tasks, optionally filtered by status."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if a row was removed."""
        cur = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Deserialize JSON context
        raw = d.get("context", "{}")
        if isinstance(raw, str):
            try:
                d["context"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d["context"] = {}
        # Deserialize JSON artifacts
        raw_art = d.get("artifacts", "[]")
        if isinstance(raw_art, str):
            try:
                d["artifacts"] = json.loads(raw_art)
            except (json.JSONDecodeError, TypeError):
                d["artifacts"] = []
        # Deserialize JSON warnings
        raw_warn = d.get("warnings", "[]")
        if isinstance(raw_warn, str):
            try:
                d["warnings"] = json.loads(raw_warn)
            except (json.JSONDecodeError, TypeError):
                d["warnings"] = []
        return d
