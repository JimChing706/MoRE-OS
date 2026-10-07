"""Provenance audit layer — tracks execution channels and audits deliverables.

Channel taxonomy:
  - pending:               task created but not yet routed to an executor
  - native_planner_loop:   executed via the 4-phase native_executor (P→W→V→D)
  - external_tool_chain:   executed via an external tool chain or plug-in executor
  - unknown:               unable to attribute execution (audit-flagged)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

VALID_CHANNELS = {"pending", "native_planner_loop", "external_tool_chain", "unknown"}
ChannelType = Literal["pending", "native_planner_loop", "external_tool_chain", "unknown"]

_AUDIT_TOKEN_THRESHOLD = 4000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance_records (
    task_id       TEXT NOT NULL,
    seq           INTEGER NOT NULL DEFAULT 0,
    channel       TEXT NOT NULL DEFAULT 'unknown',
    token_count   INTEGER NOT NULL DEFAULT 0,
    files_written INTEGER NOT NULL DEFAULT 0,
    iterations    INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT NOT NULL DEFAULT '{}',
    created_iso   TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_provenance_task ON provenance_records(task_id);
"""


@dataclass
class AuditReport:
    deliverable_blocked: bool
    execution_channel: str
    files_written_count: int
    total_iterations: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deliverable_blocked": self.deliverable_blocked,
            "execution_channel": self.execution_channel,
            "files_written_count": self.files_written_count,
            "total_iterations": self.total_iterations,
            "warnings": list(self.warnings),
        }


class ProvenanceLayer:
    """Thread-safe provenance tracker backed by SQLite.

    Typical usage::

        layer = ProvenanceLayer("/tmp/provenance.db")
        layer.enroll("task_abc", "pending")
        layer.mark("task_abc", "native_planner_loop", token_count=2500, files_written=5)
        report = layer.audit("task_abc")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            data_dir = Path(__file__).resolve().parents[3] / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "provenance.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def enroll(self, task_id: str, channel: ChannelType = "pending") -> None:
        """Register a task with an initial channel.

        Creates a zero-seed provenance record so subsequent ``mark`` calls
        have a baseline.
        """
        if channel not in VALID_CHANNELS:
            channel = "unknown"
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO provenance_records
                   (task_id, seq, channel, token_count, files_written, iterations,
                    payload_json, created_iso)
                   VALUES (?, 0, ?, 0, 0, 0, '{}', ?)""",
                (task_id, channel, self._now_iso()),
            )
            self._conn.commit()

    def mark(
        self,
        task_id: str,
        channel: ChannelType | None = None,
        *,
        token_count: int | None = None,
        files_written: int | None = None,
        iterations: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append a provenance marker row for a task.

        Parameters are additive: unset fields inherit from the latest
        record of the same ``task_id`` (or 0/empty).
        """
        if channel is not None and channel not in VALID_CHANNELS:
            channel = "unknown"
        with self._lock:
            latest = self._conn.execute(
                "SELECT * FROM provenance_records WHERE task_id = ? ORDER BY seq DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if latest is None:
                base_channel = channel or "pending"
                base_tokens = 0
                base_files = 0
                base_iter = 0
                base_seq = 0
            else:
                base_channel = channel or latest["channel"]
                base_tokens = latest["token_count"]
                base_files = latest["files_written"]
                base_iter = latest["iterations"]
                base_seq = int(latest["seq"])
            new_seq = base_seq + 1
            if token_count is not None:
                base_tokens = int(token_count)
            if files_written is not None:
                base_files = int(files_written)
            if iterations is not None:
                base_iter = int(iterations)
            payload_str = json.dumps(payload or {}, ensure_ascii=False)
            self._conn.execute(
                """INSERT OR REPLACE INTO provenance_records
                   (task_id, seq, channel, token_count, files_written, iterations,
                    payload_json, created_iso)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    new_seq,
                    base_channel,
                    base_tokens,
                    base_files,
                    base_iter,
                    payload_str,
                    self._now_iso(),
                ),
            )
            self._conn.commit()

    @staticmethod
    def _resolve_task_blocking_level(task_id: str) -> str | None:
        try:
            import pathlib as _pl

            base = _pl.Path(__file__).resolve().parents[3] / "data" / "tasks.db"
            import os as _os

            env_path = _os.environ.get("MORE_TASKS_DB_PATH")
            p = _pl.Path(env_path) if env_path else _pl.Path(base)
            if not p.is_file():
                return None
            with sqlite3.connect(str(p), timeout=3.0) as conn:
                row = conn.execute(
                    "SELECT context FROM tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                if row is None:
                    return None
                try:
                    ctx = json.loads(row[0] or "{}")
                except Exception:  # noqa: BLE001
                    return None
                if isinstance(ctx, dict) and ctx.get("validation_blocking_level"):
                    return str(ctx["validation_blocking_level"]).lower()
        except Exception:  # noqa: BLE001
            return None
        return None

    def audit(self, task_id: str) -> AuditReport:
        """Return a structured audit report for a task.

        Audit rules:
          * deliverable_blocked=True when the latest channel is
            ``unknown`` (or empty/pending never enrolled) AND
            token_count > AUDIT_TOKEN_THRESHOLD (4000).
          * Otherwise deliverable_blocked=False.
          * validation_blocking_level ∈ {off, warn} 时跳过 V-03a/V-04 release-block。
        """
        warnings: list[str] = []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provenance_records WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
        if not rows:
            warnings.append(f"No provenance records found for task_id={task_id!r}")
            return AuditReport(
                deliverable_blocked=False,
                execution_channel="unknown",
                files_written_count=0,
                total_iterations=0,
                warnings=warnings,
            )
        latest = rows[-1]
        channel = str(latest["channel"] or "unknown").strip() or "unknown"
        token_count = int(latest["token_count"] or 0)
        files_written = int(latest["files_written"] or 0)
        iterations = int(latest["iterations"] or 0)

        try:
            latest_payload_local = json.loads(latest["payload_json"] or "{}")
        except Exception:  # noqa: BLE001
            latest_payload_local = {}
        bl_src = None
        if isinstance(latest_payload_local, dict):
            bl_src = latest_payload_local.get("validation_blocking_level")
            if isinstance(latest_payload_local.get("payload"), dict):
                bl_src = bl_src or latest_payload_local["payload"].get("validation_blocking_level")
        if bl_src is None:
            bl_src = self._resolve_task_blocking_level(task_id)
        blocking_level = str(bl_src).lower() if bl_src is not None else "hard_block"
        is_blocking_disabled = blocking_level in {"off", "warn"}

        blocked = False
        if channel == "unknown":
            if token_count > _AUDIT_TOKEN_THRESHOLD:
                blocked = True
                warnings.append(
                    f"audit_needed: channel=unknown, tokens={token_count} > {_AUDIT_TOKEN_THRESHOLD}"
                )
            else:
                warnings.append(
                    f"channel=unknown but tokens={token_count} <= {_AUDIT_TOKEN_THRESHOLD}; not blocking"
                )

        if isinstance(latest_payload_local, dict):
            vpass = latest_payload_local.get("validation_pass")
            if vpass is None:
                nested = latest_payload_local.get("payload") or {}
                if isinstance(nested, dict):
                    vpass = nested.get("validation_pass")
            if vpass is False and not is_blocking_disabled:
                blocked = True
                warnings.append("deliverable blocked: validation_pass=False on the final record")
            elif vpass is False and is_blocking_disabled:
                warnings.append(
                    f"validation_pass=False but blocking_level={blocking_level}; skip release-block"
                )
            if latest_payload_local.get("final_status") == "failed" and not is_blocking_disabled:
                blocked = True
                warnings.append("deliverable blocked: final_status=failed on the latest record")
            elif latest_payload_local.get("final_status") == "failed" and is_blocking_disabled:
                warnings.append(
                    f"final_status=failed but blocking_level={blocking_level}; skip release-block"
                )
        return AuditReport(
            deliverable_blocked=blocked,
            execution_channel=channel,
            files_written_count=files_written,
            total_iterations=iterations,
            warnings=warnings,
        )

    def audit_with_status_override(
        self,
        task_id: str,
        *,
        raw_status: str = "unknown",
        raw_progress: int = 0,
    ) -> tuple[AuditReport, str, int]:
        """Return (report, overridden_status, overridden_progress)。

        阻断策略（HARD_BLOCK 等级）：
          - 若 report.deliverable_blocked=True：
              status="failed" / progress=min(90, max(0, raw_progress))
          - 否则保持原值
        """
        report = self.audit(task_id)
        if report.deliverable_blocked:
            try:
                p = int(raw_progress)
            except (TypeError, ValueError):
                p = 90
            try:
                p_clamped = int(min(max(p, 0), 90))
            except Exception:  # noqa: BLE001
                p_clamped = 90
            return report, "failed", p_clamped
        return report, str(raw_status), int(raw_progress)

    def list_records(self, task_id: str) -> list[dict[str, Any]]:
        """Return raw provenance rows for debugging/testing."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provenance_records WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload_json") or "{}")
            except Exception:  # noqa: BLE001
                d["payload"] = {}
            out.append(d)
        return out

    def reset(self, task_id: str | None = None) -> None:
        """Delete records for one task (or all) — testing helper."""
        with self._lock:
            if task_id is None:
                self._conn.execute("DELETE FROM provenance_records")
            else:
                self._conn.execute("DELETE FROM provenance_records WHERE task_id = ?", (task_id,))
            self._conn.commit()

    def get_channel_counters(self) -> dict[str, int]:
        """Return per-channel distinct-task counters.

        Analog of ``more_provenance_tasks_total{channel="..."}`` without
        introducing a Prometheus client dependency. Each distinct task_id
        is attributed to the channel of its *latest* (max seq) record.
        """
        counters: dict[str, int] = dict.fromkeys(VALID_CHANNELS, 0)
        with self._lock:
            rows = self._conn.execute(
                """SELECT channel, COUNT(DISTINCT task_id) AS cnt
                   FROM provenance_records a
                   WHERE seq = (SELECT MAX(seq) FROM provenance_records b
                                 WHERE b.task_id = a.task_id)
                   GROUP BY channel"""
            ).fetchall()
        for r in rows:
            ch = str(r["channel"] or "unknown").strip() or "unknown"
            if ch not in counters:
                counters["unknown"] = counters.get("unknown", 0) + int(r["cnt"] or 0)
            else:
                counters[ch] = counters[ch] + int(r["cnt"] or 0)
        return counters

    def list_all_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return latest records per distinct task_id — overview dashboard."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT a.* FROM provenance_records a
                   WHERE seq = (SELECT MAX(seq) FROM provenance_records b
                                 WHERE b.task_id = a.task_id)
                   ORDER BY created_iso DESC
                   LIMIT ?""",
                (int(limit),),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload_json") or "{}")
            except Exception:  # noqa: BLE001
                d["payload"] = {}
            out.append(d)
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Module-level singleton for convenience (used by the tasks router).
# Callers may always construct their own ProvenanceLayer(db_path=...)
# when isolation is desired (e.g. tests).
# ----------------------------------------------------------------------

_DEFAULT_DB_ENV = "MORE_PROVENANCE_DB"


def _default_db_path() -> Path:
    env = os.environ.get(_DEFAULT_DB_ENV)
    if env:
        return Path(env)
    data_dir = Path(__file__).resolve().parents[3] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "provenance.db"


_default_layer: ProvenanceLayer | None = None
_default_lock = threading.RLock()


def get_default_layer() -> ProvenanceLayer:
    global _default_layer
    with _default_lock:
        if _default_layer is None:
            _default_layer = ProvenanceLayer(_default_db_path())
    return _default_layer


__all__ = [
    "VALID_CHANNELS",
    "AuditReport",
    "ChannelType",
    "ProvenanceLayer",
    "get_default_layer",
]
