"""交付台账 — 代码产出的全链路可追溯 + 交付成功率量化。

对应三大硬伤中的"交付可信度"：

* **状态追踪**：每一次交付写入一行记录（task_id → version → status → 时间）。
* **权责标记**：记录 ``actor``（发起主体）、``provider/model``（执行主体）、
  ``verdict``（控制器裁决）与 ``gates``（多维校验结论）。
* **版本管理**：同一 task_id 的多次交付按 ``version`` 递增，可 diff 历史。
* **可追溯**：``artifact_sha256`` + ``trace_id`` 把交付物与执行轨迹绑定。
* **量化模型**：``stats()`` 输出交付成功率（按任务类型/时间窗切分）。

设计原则与 ``governance.observability`` 一致：只追加、线程安全、
写入失败不影响用户链路（但会通过 ``last_error`` 暴露，而不是静默吞掉）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

__all__ = ["DeliveryLedger", "DeliveryRecord", "get_default_ledger", "set_default_ledger"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id     TEXT PRIMARY KEY,
    ts              REAL NOT NULL,
    task_id         TEXT NOT NULL,
    task_type       TEXT NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    artifact_sha256 TEXT NOT NULL DEFAULT '',
    artifact_chars  INTEGER NOT NULL DEFAULT 0,
    verdict         TEXT NOT NULL DEFAULT '',
    gates_passed    INTEGER NOT NULL DEFAULT 0,
    gates_json      TEXT NOT NULL DEFAULT '{}',
    actor           TEXT NOT NULL DEFAULT '',
    provider        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    trace_id        TEXT NOT NULL DEFAULT '',
    request_excerpt TEXT NOT NULL DEFAULT '',
    cause           TEXT NOT NULL DEFAULT '',
    is_infra        INTEGER NOT NULL DEFAULT 0,
    stage_timings   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_deliveries_task ON deliveries(task_id, version);
CREATE INDEX IF NOT EXISTS idx_deliveries_ts   ON deliveries(ts);
CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status);
"""

#: status 语义
STATUS_DELIVERED = "delivered"
STATUS_BLOCKED = "blocked"  # 校验闸门拦截，产物不可信
STATUS_FAILED = "failed"  # 执行失败

_TERMINAL_STATUSES = (STATUS_DELIVERED,)


def _default_db_path() -> Path:
    env = os.environ.get("MORE_DELIVERY_LEDGER_DB")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[3] / "data" / "delivery_ledger.db"


def _load_json(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class DeliveryRecord:
    delivery_id: str
    task_id: str
    task_type: str
    version: int
    status: str
    reason: str
    artifact_sha256: str
    artifact_chars: int
    verdict: str
    gates_passed: bool
    actor: str
    provider: str
    model: str
    trace_id: str
    request_excerpt: str
    ts: float
    gates: dict[str, Any] = field(default_factory=dict)
    cause: str = ""
    is_infra: bool = False
    stage_timings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "artifact_sha256": self.artifact_sha256,
            "artifact_chars": self.artifact_chars,
            "verdict": self.verdict,
            "gates_passed": self.gates_passed,
            "gates": self.gates,
            "actor": self.actor,
            "provider": self.provider,
            "model": self.model,
            "trace_id": self.trace_id,
            "request_excerpt": self.request_excerpt,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts)),
            "cause": self.cause,
            "is_infra": self.is_infra,
            "stage_timings": self.stage_timings,
        }


def _stage_percentile(rows: list[Any], q: float = 0.5) -> dict[str, float]:
    """按层聚合（默认 p50）最近交付的阶段耗时。

    D-4：把"端到端延迟"拆到 L0/L1/L3/L4…，用于定位瓶颈层。
    """
    buckets: dict[str, list[float]] = {}
    for row in rows:
        try:
            timings = json.loads(
                (row["stage_timings"] if "stage_timings" in row.keys() else "{}") or "{}"  # noqa: SIM118
            )
        except Exception:  # noqa: BLE001, S112
            continue
        if not isinstance(timings, dict):
            continue
        for layer, value in timings.items():
            try:
                buckets.setdefault(str(layer), []).append(float(value))
            except (TypeError, ValueError):
                continue
    out: dict[str, float] = {}
    for layer, values in buckets.items():
        values.sort()
        idx = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
        out[layer] = round(values[idx], 1)
    return dict(sorted(out.items()))


from ..governance.observability import success_trend as _success_trend


class DeliveryLedger:
    """Append-only delivery ledger backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else _default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.last_error: str = ""
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()

    def _migrate(self) -> None:
        """为既有台账补齐列（幂等）。"""
        cols = {str(r["name"]) for r in self._conn.execute("PRAGMA table_info(deliveries)")}
        if "cause" not in cols:
            self._conn.execute("ALTER TABLE deliveries ADD COLUMN cause TEXT NOT NULL DEFAULT ''")
        if "is_infra" not in cols:
            self._conn.execute(
                "ALTER TABLE deliveries ADD COLUMN is_infra INTEGER NOT NULL DEFAULT 0"
            )
        if "stage_timings" not in cols:
            self._conn.execute(
                "ALTER TABLE deliveries ADD COLUMN stage_timings TEXT NOT NULL DEFAULT '{}'"
            )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_cause ON deliveries(cause)")

    @property
    def db_path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def next_version(self, task_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) v FROM deliveries WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["v"]) + 1

    def record(
        self,
        *,
        task_id: str,
        status: str,
        task_type: str = "",
        reason: str = "",
        artifact: str = "",
        verdict: str = "",
        gates: dict[str, Any] | None = None,
        gates_passed: bool = True,
        actor: str = "",
        provider: str = "",
        model: str = "",
        trace_id: str = "",
        request_excerpt: str = "",
        cause: str = "",
        is_infra: bool = False,
        stage_timings: dict[str, Any] | None = None,
    ) -> DeliveryRecord:
        """写入一次交付。版本号按 task_id 自增。写失败不抛异常但会记录 last_error。"""
        gates = gates or {}
        record = DeliveryRecord(
            delivery_id=f"dlv_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            task_type=task_type,
            version=self.next_version(task_id),
            status=status,
            reason=reason,
            artifact_sha256=_sha256(artifact),
            artifact_chars=len(artifact or ""),
            verdict=verdict,
            gates_passed=bool(gates_passed),
            actor=actor,
            provider=provider,
            model=model,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:10]}",
            request_excerpt=(request_excerpt or "")[:200],
            ts=time.time(),
            gates=gates,
            cause=cause or "",
            is_infra=bool(is_infra),
            stage_timings=dict(stage_timings or {}),
        )
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO deliveries
                       (delivery_id, ts, task_id, task_type, version, status, reason,
                        artifact_sha256, artifact_chars, verdict, gates_passed,
                        gates_json, actor, provider, model, trace_id, request_excerpt,
                        cause, is_infra, stage_timings)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record.delivery_id,
                        record.ts,
                        record.task_id,
                        record.task_type,
                        record.version,
                        record.status,
                        record.reason,
                        record.artifact_sha256,
                        record.artifact_chars,
                        record.verdict,
                        1 if record.gates_passed else 0,
                        json.dumps(gates, ensure_ascii=False),
                        record.actor,
                        record.provider,
                        record.model,
                        record.trace_id,
                        record.request_excerpt,
                        record.cause,
                        1 if record.is_infra else 0,
                        json.dumps(record.stage_timings, ensure_ascii=False),
                    ),
                )
                self._conn.commit()
            self.last_error = ""
        except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
            self.last_error = str(exc)
        return record

    def _row(self, row: sqlite3.Row) -> DeliveryRecord:
        try:
            gates = json.loads(row["gates_json"] or "{}")
        except Exception:  # noqa: BLE001
            gates = {}
        return DeliveryRecord(
            delivery_id=row["delivery_id"],
            task_id=row["task_id"],
            task_type=row["task_type"],
            version=int(row["version"]),
            status=row["status"],
            reason=row["reason"],
            artifact_sha256=row["artifact_sha256"],
            artifact_chars=int(row["artifact_chars"]),
            verdict=row["verdict"],
            gates_passed=bool(row["gates_passed"]),
            actor=row["actor"],
            provider=row["provider"],
            model=row["model"],
            trace_id=row["trace_id"],
            request_excerpt=row["request_excerpt"],
            ts=float(row["ts"]),
            gates=gates,
            cause=(row["cause"] if "cause" in row.keys() else "") or "",  # noqa: SIM118
            is_infra=bool(row["is_infra"]) if "is_infra" in row.keys() else False,  # noqa: SIM118
            stage_timings=_load_json(row["stage_timings"]) if "stage_timings" in row.keys() else {},  # noqa: SIM118
        )

    def list(self, *, task_id: str | None = None, limit: int = 50) -> list[DeliveryRecord]:
        try:
            with self._lock:
                if task_id:
                    rows = self._conn.execute(
                        "SELECT * FROM deliveries WHERE task_id = ? ORDER BY version DESC LIMIT ?",
                        (task_id, int(limit)),
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM deliveries ORDER BY ts DESC LIMIT ?", (int(limit),)
                    ).fetchall()
            return [self._row(r) for r in rows]
        except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
            self.last_error = str(exc)
            return []

    def latest(self, task_id: str) -> DeliveryRecord | None:
        rows = self.list(task_id=task_id, limit=1)
        return rows[0] if rows else None

    # 默认双窗口：近 1h（当前状态）与 24h（历史累积）
    DEFAULT_WINDOWS: ClassVar[dict[str, int]] = {"1h": 3600, "24h": 86400}

    def stats_windows(self, windows: dict[str, int] | None = None) -> dict[str, Any]:
        """多窗口成功率 + 趋势。

        单窗口会把"历史故障期样本"混进当前判断（评估发现 A-3）；多窗口可区分。
        返回 ``{"windows": {label: stats}, "trend": improving|declining|stable}``。
        """
        wins = windows or dict(self.DEFAULT_WINDOWS)
        by_window = {label: self.stats(sec) for label, sec in wins.items()}
        recent = by_window.get("1h") or next(iter(by_window.values()), {})
        base = by_window.get("24h") or recent
        return {
            "windows": by_window,
            "trend": _success_trend(
                float(recent.get("success_rate") or 0.0),
                float(base.get("success_rate") or 0.0),
                recent_samples=int(recent.get("total") or 0),
            ),
        }

    def stats(self, window_s: int = 24 * 3600) -> dict[str, Any]:
        """交付成功率量化模型：按总量/状态/任务类型切分。"""
        try:
            since = time.time() - max(0, int(window_s))
            with self._lock:
                rows = self._conn.execute(
                    "SELECT task_type, status, gates_passed, artifact_chars, cause, is_infra, stage_timings "
                    "FROM deliveries WHERE ts >= ?",
                    (since,),
                ).fetchall()
            total = len(rows)
            delivered = sum(1 for r in rows if r["status"] == STATUS_DELIVERED)
            by_cause: dict[str, int] = {}
            for r in rows:
                if r["status"] == STATUS_BLOCKED:
                    key = (r["cause"] if "cause" in r.keys() else "") or "unspecified"  # noqa: SIM118
                    by_cause[key] = by_cause.get(key, 0) + 1
            infra_blocked = sum(
                1
                for r in rows
                if r["status"] == STATUS_BLOCKED
                and ("is_infra" in r.keys() and bool(r["is_infra"]))  # noqa: SIM118
            )
            blocked = sum(1 for r in rows if r["status"] == STATUS_BLOCKED)
            failed = sum(1 for r in rows if r["status"] == STATUS_FAILED)
            by_type: dict[str, dict[str, Any]] = {}
            for r in rows:
                t = r["task_type"] or "unknown"
                slot = by_type.setdefault(
                    t, {"total": 0, "delivered": 0, "blocked": 0, "failed": 0}
                )
                slot["total"] += 1
                if r["status"] == STATUS_DELIVERED:
                    slot["delivered"] += 1
                elif r["status"] == STATUS_BLOCKED:
                    slot["blocked"] += 1
                elif r["status"] == STATUS_FAILED:
                    slot["failed"] += 1
            for slot in by_type.values():
                slot["success_rate"] = (
                    round(slot["delivered"] / slot["total"], 3) if slot["total"] else 0.0
                )
            return {
                "window_s": int(window_s),
                "total": total,
                "delivered": delivered,
                "blocked": blocked,
                "failed": failed,
                "success_rate": round(delivered / total, 3) if total else 0.0,
                "gate_pass_rate": round(sum(1 for r in rows if r["gates_passed"]) / total, 3)
                if total
                else 0.0,
                "avg_artifact_chars": round(
                    sum(int(r["artifact_chars"] or 0) for r in rows) / total, 1
                )
                if total
                else 0.0,
                "by_task_type": by_type,
                "stage_ms_p50": _stage_percentile(rows),
                "blocked_by_cause": dict(sorted(by_cause.items(), key=lambda kv: -kv[1])),
                "infra_blocked": infra_blocked,
                "last_error": self.last_error,
            }
        except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
            return {"window_s": int(window_s), "total": 0, "error": str(exc)}


_default_ledger: DeliveryLedger | None = None
_default_lock = threading.RLock()


def get_default_ledger() -> DeliveryLedger:
    global _default_ledger
    with _default_lock:
        if _default_ledger is None:
            _default_ledger = DeliveryLedger()
    return _default_ledger


def set_default_ledger(ledger: DeliveryLedger | None) -> None:
    global _default_ledger
    with _default_lock:
        _default_ledger = ledger
