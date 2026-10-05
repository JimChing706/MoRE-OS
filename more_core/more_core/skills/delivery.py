"""技能交付台账 —— 结构化归档全部技能的交付信息与验收状态。

归档字段（标准化、可追溯）::

    skill_id / name / description / category / version
    dependencies / deployment / maintainer / config_schema
    status (draft|accepted|deprecated) / evidence / archived_at / updated_at

设计要点：
* 单文件 SQLite（默认 ``data/skill_deliverables.db``，可用
  ``MORE_SKILL_LEDGER_DB`` 覆盖），``archive()`` 为 **upsert**，
  重复归档只更新 ``updated_at``，保留 ``archived_at`` 首次时间。
* 所有写操作 ``try/except`` 包裹——台账不得影响技能运行。
* ``stats()`` 给出完整性/验收率，供全景评估直接消费。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

STATUS_DRAFT = "draft"
STATUS_ACCEPTED = "accepted"
STATUS_DEPRECATED = "deprecated"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_deliverables (
    skill_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    version       TEXT NOT NULL DEFAULT '',
    dependencies  TEXT NOT NULL DEFAULT '[]',
    deployment    TEXT NOT NULL DEFAULT '{}',
    maintainer    TEXT NOT NULL DEFAULT '',
    config_schema TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'draft',
    evidence      TEXT NOT NULL DEFAULT '{}',
    archived_at   REAL NOT NULL DEFAULT 0,
    updated_at    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_skill_deliver_status ON skill_deliverables(status);
"""


def _load(raw: Any, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


@dataclass(slots=True)
class SkillDeliverable:
    """一条技能交付台账记录。"""

    skill_id: str
    name: str
    description: str
    category: str
    version: str
    dependencies: list[str] = field(default_factory=list)
    deployment: dict[str, Any] = field(default_factory=dict)
    maintainer: str = ""
    config_schema: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_DRAFT
    evidence: dict[str, Any] = field(default_factory=dict)
    archived_at: float = 0.0
    updated_at: float = 0.0

    @property
    def complete(self) -> bool:
        """台账必备信息是否齐全（名称/描述/版本/责任人/依赖）。"""
        return bool(
            self.skill_id
            and self.name
            and self.description
            and self.version
            and self.maintainer
        )

    @property
    def accepted(self) -> bool:
        return self.status == STATUS_ACCEPTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "dependencies": list(self.dependencies),
            "deployment": dict(self.deployment),
            "maintainer": self.maintainer,
            "config_schema": dict(self.config_schema),
            "status": self.status,
            "accepted": self.accepted,
            "complete": self.complete,
            "evidence": dict(self.evidence),
            "archived_at": self.archived_at,
            "updated_at": self.updated_at,
        }


class SkillDeliveryLedger:
    """技能交付台账（SQLite）。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.last_error: str = ""
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
        except Exception as exc:  # pragma: no cover - 台账不可用不影响主链路
            self.last_error = str(exc)
            _log.warning("skill ledger init failed: %s", exc)

    # -- writes ------------------------------------------------------------

    def archive(
        self,
        meta: Any,
        *,
        status: str = STATUS_ACCEPTED,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        """归档/更新一条技能交付记录（upsert）。返回是否成功。"""
        now = time.time()
        try:
            with self._lock, self._connect() as conn:
                existing = conn.execute(
                    "SELECT archived_at FROM skill_deliverables WHERE skill_id = ?",
                    (meta.id,),
                ).fetchone()
                archived_at = existing["archived_at"] if existing else now
                conn.execute(
                    """INSERT INTO skill_deliverables
                       (skill_id, name, description, category, version, dependencies,
                        deployment, maintainer, config_schema, status, evidence,
                        archived_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(skill_id) DO UPDATE SET
                         name=excluded.name, description=excluded.description,
                         category=excluded.category, version=excluded.version,
                         dependencies=excluded.dependencies, deployment=excluded.deployment,
                         maintainer=excluded.maintainer, config_schema=excluded.config_schema,
                         status=excluded.status, evidence=excluded.evidence,
                         updated_at=excluded.updated_at""",
                    (
                        meta.id,
                        meta.name,
                        meta.description,
                        meta.category.value,
                        meta.version,
                        json.dumps(list(meta.dependencies), ensure_ascii=False),
                        json.dumps(dict(meta.deployment), ensure_ascii=False),
                        meta.maintainer,
                        json.dumps(dict(meta.config_schema), ensure_ascii=False),
                        status,
                        json.dumps(evidence or {}, ensure_ascii=False),
                        archived_at,
                        now,
                    ),
                )
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self.last_error = str(exc)
            return False

    def mark_accepted(self, skill_id: str) -> bool:
        """把指定技能的状态置为已验收。"""
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "UPDATE skill_deliverables SET status = ?, updated_at = ? WHERE skill_id = ?",
                    (STATUS_ACCEPTED, time.time(), skill_id),
                )
                return cur.rowcount > 0
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return False

    # -- reads -------------------------------------------------------------

    def get(self, skill_id: str) -> SkillDeliverable | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM skill_deliverables WHERE skill_id = ?", (skill_id,)
                ).fetchone()
            return self._row_to_record(row) if row else None
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return None

    def list(self) -> list[SkillDeliverable]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM skill_deliverables ORDER BY skill_id"
                ).fetchall()
            return [self._row_to_record(r) for r in rows]
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            return []

    def stats(self) -> dict[str, Any]:
        records = self.list()
        total = len(records)
        accepted = sum(1 for r in records if r.accepted)
        complete = sum(1 for r in records if r.complete)
        by_status: dict[str, int] = {}
        for r in records:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        return {
            "total": total,
            "accepted": accepted,
            "complete": complete,
            "acceptance_rate": round(accepted / total, 3) if total else 0.0,
            "completeness_rate": round(complete / total, 3) if total else 0.0,
            "by_status": by_status,
            "incomplete": [r.skill_id for r in records if not r.complete],
            "ledger_db": str(self.db_path),
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> SkillDeliverable:
        return SkillDeliverable(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            category=row["category"],
            version=row["version"],
            dependencies=_load(row["dependencies"], []),
            deployment=_load(row["deployment"], {}),
            maintainer=row["maintainer"],
            config_schema=_load(row["config_schema"], {}),
            status=row["status"],
            evidence=_load(row["evidence"], {}),
            archived_at=float(row["archived_at"] or 0),
            updated_at=float(row["updated_at"] or 0),
        )


_INSTANCE: SkillDeliveryLedger | None = None
_INSTANCE_LOCK = threading.Lock()


def _default_path() -> Path:
    env = os.getenv("MORE_SKILL_LEDGER_DB")
    if env:
        return Path(env)
    root = os.getenv("MORE_PROJECT_ROOT") or os.getcwd()
    return Path(root) / "data" / "skill_deliverables.db"


def get_default_skill_ledger() -> SkillDeliveryLedger:
    """进程内单例。"""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = SkillDeliveryLedger(_default_path())
    return _INSTANCE


def set_default_skill_ledger(ledger: SkillDeliveryLedger | None) -> None:
    """替换单例（测试隔离用）。"""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = ledger


def archive_skill_manager(skill_manager: Any, *, status: str = STATUS_ACCEPTED) -> int:
    """把技能管理器里的全部技能归档到台账。返回成功条数。"""
    ledger = get_default_skill_ledger()
    ok = 0
    for meta in skill_manager.list_skills():
        evidence = {
            "config_schema_present": bool(meta.config_schema),
            "schema_required_fields": list(meta.config_schema.get("required", []) or []),
            "verified_version": meta.version,
        }
        if ledger.archive(meta, status=status, evidence=evidence):
            ok += 1
    return ok
