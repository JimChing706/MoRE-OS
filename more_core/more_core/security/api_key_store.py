"""API key registry — scoped, expiring, revocable keys stored as peppered hashes.

This is the *management plane* behind ``MORE_API_KEY``.  The legacy
single-key env var keeps working (see ``api/server.py``); this store adds what
an operational deployment needs:

* **storage** — SQLite, only ``HMAC-SHA256(pepper, key)`` is persisted, never
  the raw secret;
* **scopes** — each key carries a list of scope strings (``tasks:execute``,
  ``admin:apikeys``, …); ``*`` means wildcard;
* **expiry** — ``expires_at`` is checked on every verification;
* **revocation / rotation** — revoke is immediate, rotate can keep the old key
  alive for a grace window so clients migrate without downtime;
* **audit-friendly metadata** — ``key_id``, label, prefix, last_used_at.

Usage::

    store = APIKeyStore("data/api_keys.db")
    raw, record = store.issue(label="ci", scopes=["tasks:execute"], ttl_seconds=86400)
    store.verify(raw)          # -> APIKeyRecord | None
    store.rotate(record.key_id, grace_seconds=3600)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "APIKeyRecord",
    "APIKeyStore",
    "WILDCARD_SCOPE",
    "get_default_store",
    "set_default_store",
    "hash_api_key",
    "new_key_id",
]

#: Scope that grants every permission (used by the legacy env-var key).
WILDCARD_SCOPE = "*"

#: Default key lifetime when the caller does not specify one (None = no expiry).
DEFAULT_TTL_SECONDS: int | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key_id        TEXT PRIMARY KEY,
    label         TEXT NOT NULL DEFAULT '',
    prefix        TEXT NOT NULL DEFAULT '',
    key_hash      TEXT NOT NULL UNIQUE,
    scopes        TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    expires_at    TEXT,
    revoked_at    TEXT,
    last_used_at  TEXT,
    rotated_from  TEXT,
    -- 分派归属（谁在用这把钥匙）
    owner         TEXT NOT NULL DEFAULT '',
    consumer      TEXT NOT NULL DEFAULT '',
    purpose       TEXT NOT NULL DEFAULT '',
    issued_by     TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL DEFAULT '',
    -- 配额与用量
    quota_per_min INTEGER,
    call_count    INTEGER NOT NULL DEFAULT 0,
    denied_count  INTEGER NOT NULL DEFAULT 0,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    first_used_at TEXT,
    last_used_ip  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_revoked ON api_keys(revoked_at);
-- 注意：owner/consumer 索引在 _migrate() 中创建（老库需先 ALTER TABLE 补列）

-- 逐次调用明细（用于按分钟配额与用量报表；按天裁剪）
CREATE TABLE IF NOT EXISTS api_key_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id     TEXT NOT NULL,
    ts         REAL NOT NULL,
    endpoint   TEXT NOT NULL DEFAULT '',
    status     INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    tokens     INTEGER NOT NULL DEFAULT 0,
    ip         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON api_key_usage(key_id, ts);
"""

_PEPPER_FILENAME = ".api_key_pepper"
_PEPPER_BYTES = 32


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(moment: _dt.datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _parse(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def new_key_id() -> str:
    """Return a short, non-secret public identifier for a key."""
    return f"key_{secrets.token_hex(6)}"


def _default_db_path() -> Path:
    env = os.environ.get("MORE_API_KEY_DB")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[3] / "data" / "api_keys.db"


def _load_pepper(db_path: Path) -> bytes:
    """Resolve the HMAC pepper: env var first, else a 0600 file next to the DB."""
    env = os.environ.get("MORE_API_KEY_PEPPER")
    if env:
        return env.encode("utf-8")

    pepper_path = db_path.parent / _PEPPER_FILENAME
    if pepper_path.exists():
        data = pepper_path.read_bytes()
        if len(data) >= _PEPPER_BYTES:
            return data

    pepper_path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(_PEPPER_BYTES)
    tmp = pepper_path.with_suffix(".tmp")
    tmp.write_bytes(value)
    os.chmod(tmp, 0o600)
    os.replace(tmp, pepper_path)
    return pepper_path.read_bytes()


def hash_api_key(raw_key: str, pepper: bytes) -> str:
    """Return the peppered HMAC-SHA256 digest that is persisted for *raw_key*."""
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class APIKeyRecord:
    """Public (non-secret) metadata for one issued API key."""

    key_id: str
    label: str
    prefix: str
    scopes: tuple[str, ...]
    created_at: str
    expires_at: str | None = None
    revoked_at: str | None = None
    last_used_at: str | None = None
    rotated_from: str | None = None
    # 分派归属
    owner: str = ""
    consumer: str = ""
    purpose: str = ""
    issued_by: str = ""
    channel: str = ""
    # 配额与用量
    quota_per_min: int | None = None
    call_count: int = 0
    denied_count: int = 0
    tokens_used: int = 0
    first_used_at: str | None = None
    last_used_ip: str = ""
    _key_hash: str = field(default="", repr=False)

    @property
    def expired(self) -> bool:
        expiry = _parse(self.expires_at)
        return expiry is not None and expiry <= _now()

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def active(self) -> bool:
        return not self.expired and not self.revoked

    def has_scope(self, scope: str) -> bool:
        return WILDCARD_SCOPE in self.scopes or scope in self.scopes

    def as_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "label": self.label,
            "prefix": self.prefix,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "last_used_at": self.last_used_at,
            "rotated_from": self.rotated_from,
            "status": "revoked" if self.revoked else ("expired" if self.expired else "active"),
            "owner": self.owner,
            "consumer": self.consumer,
            "purpose": self.purpose,
            "issued_by": self.issued_by,
            "channel": self.channel,
            "quota_per_min": self.quota_per_min,
            "call_count": self.call_count,
            "denied_count": self.denied_count,
            "tokens_used": self.tokens_used,
            "first_used_at": self.first_used_at,
            "last_used_ip": self.last_used_ip,
        }


def _row_to_record(row: sqlite3.Row) -> APIKeyRecord:
    try:
        scopes = tuple(json.loads(row["scopes"] or "[]"))
    except (TypeError, ValueError):
        scopes = ()
    return APIKeyRecord(
        key_id=row["key_id"],
        label=row["label"],
        prefix=row["prefix"],
        scopes=scopes,
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        last_used_at=row["last_used_at"],
        rotated_from=row["rotated_from"],
        owner=row["owner"] if "owner" in row.keys() else "",
        consumer=row["consumer"] if "consumer" in row.keys() else "",
        purpose=row["purpose"] if "purpose" in row.keys() else "",
        issued_by=row["issued_by"] if "issued_by" in row.keys() else "",
        channel=row["channel"] if "channel" in row.keys() else "",
        quota_per_min=row["quota_per_min"] if "quota_per_min" in row.keys() else None,
        call_count=int(row["call_count"] or 0) if "call_count" in row.keys() else 0,
        denied_count=int(row["denied_count"] or 0) if "denied_count" in row.keys() else 0,
        tokens_used=int(row["tokens_used"] or 0) if "tokens_used" in row.keys() else 0,
        first_used_at=row["first_used_at"] if "first_used_at" in row.keys() else None,
        last_used_ip=row["last_used_ip"] if "last_used_ip" in row.keys() else "",
        _key_hash=row["key_hash"],
    )


class APIKeyStore:
    """SQLite-backed registry of issued API keys."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pepper = _load_pepper(self._db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()

    def _migrate(self) -> None:
        """为既有部署补齐新增列（幂等）。"""
        existing = {
            str(r["name"]) for r in self._conn.execute("PRAGMA table_info(api_keys)")
        }
        additions = {
            "owner": "TEXT NOT NULL DEFAULT ''",
            "consumer": "TEXT NOT NULL DEFAULT ''",
            "purpose": "TEXT NOT NULL DEFAULT ''",
            "issued_by": "TEXT NOT NULL DEFAULT ''",
            "channel": "TEXT NOT NULL DEFAULT ''",
            "quota_per_min": "INTEGER",
            "call_count": "INTEGER NOT NULL DEFAULT 0",
            "denied_count": "INTEGER NOT NULL DEFAULT 0",
            "tokens_used": "INTEGER NOT NULL DEFAULT 0",
            "first_used_at": "TEXT",
            "last_used_ip": "TEXT NOT NULL DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE api_keys ADD COLUMN {column} {ddl}")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner, consumer)"
        )

    # -- introspection -----------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- write plane -------------------------------------------------------

    def issue(
        self,
        *,
        raw_key: str,
        label: str = "",
        scopes: list[str] | None = None,
        ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
        key_id: str | None = None,
        rotated_from: str | None = None,
        owner: str = "",
        consumer: str = "",
        purpose: str = "",
        issued_by: str = "",
        channel: str = "",
        quota_per_min: int | None = None,
    ) -> APIKeyRecord:
        """Persist *raw_key* and return its public record.

        The raw key is **not** stored; only the peppered hash is.
        """
        if not raw_key:
            raise ValueError("raw_key must be a non-empty string")

        created = _now()
        expires = created + _dt.timedelta(seconds=int(ttl_seconds)) if ttl_seconds else None
        record_id = key_id or new_key_id()
        digest = hash_api_key(raw_key, self._pepper)
        record = APIKeyRecord(
            key_id=record_id,
            label=label,
            prefix=raw_key[:10],
            scopes=tuple(scopes or [WILDCARD_SCOPE]),
            created_at=_iso(created) or "",
            expires_at=_iso(expires),
            revoked_at=None,
            last_used_at=None,
            rotated_from=rotated_from,
            owner=owner,
            consumer=consumer,
            purpose=purpose,
            issued_by=issued_by,
            channel=channel,
            quota_per_min=int(quota_per_min) if quota_per_min else None,
            _key_hash=digest,
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO api_keys
                   (key_id, label, prefix, key_hash, scopes, created_at,
                    expires_at, revoked_at, last_used_at, rotated_from,
                    owner, consumer, purpose, issued_by, channel, quota_per_min)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.key_id,
                    record.label,
                    record.prefix,
                    digest,
                    json.dumps(list(record.scopes)),
                    record.created_at,
                    record.expires_at,
                    record.revoked_at,
                    record.last_used_at,
                    record.rotated_from,
                    record.owner,
                    record.consumer,
                    record.purpose,
                    record.issued_by,
                    record.channel,
                    record.quota_per_min,
                ),
            )
            self._conn.commit()
        return record

    def register(
        self,
        *,
        label: str = "",
        scopes: list[str] | None = None,
        ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
        generator: Any = None,
        owner: str = "",
        consumer: str = "",
        purpose: str = "",
        issued_by: str = "",
        channel: str = "",
        quota_per_min: int | None = None,
    ) -> tuple[str, APIKeyRecord]:
        """Generate a fresh key (``generator`` override is for tests) and store it."""
        if generator is None:
            from .api_key_ops import generate_api_key

            raw = generate_api_key(strength="modern")
        else:
            raw = generator()
        return raw, self.issue(
            raw_key=raw, label=label, scopes=scopes, ttl_seconds=ttl_seconds,
            owner=owner, consumer=consumer, purpose=purpose,
            issued_by=issued_by, channel=channel, quota_per_min=quota_per_min,
        )

    def verify(self, raw_key: str | None, *, touch: bool = True) -> APIKeyRecord | None:
        """Return the active record for *raw_key*, or ``None`` when unusable."""
        candidate = (raw_key or "").strip()
        if not candidate:
            return None
        digest = hash_api_key(candidate, self._pepper)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?", (digest,)
            ).fetchone()
            if row is None:
                return None
            record = _row_to_record(row)
            if not record.active:
                return None
            if touch:
                now_iso = _iso(_now())
                self._conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                    (now_iso, record.key_id),
                )
                self._conn.commit()
                record = _row_to_record(
                    self._conn.execute(
                        "SELECT * FROM api_keys WHERE key_id = ?", (record.key_id,)
                    ).fetchone()
                )
            return record

    # -- usage plane -------------------------------------------------------

    def record_usage(
        self,
        key_id: str,
        *,
        endpoint: str = "",
        status: int = 0,
        latency_ms: float = 0.0,
        tokens: int = 0,
        ip: str = "",
        ts: float | None = None,
    ) -> None:
        """记录一次调用：累加计数并写一条明细（供配额与报表使用）。"""
        now_ts = float(ts if ts is not None else time.time())
        now_iso = _iso(_now())
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO api_key_usage (key_id, ts, endpoint, status,
                                                 latency_ms, tokens, ip)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (key_id, now_ts, endpoint[:200], int(status),
                     float(latency_ms), int(tokens), ip[:64]),
                )
                self._conn.execute(
                    """UPDATE api_keys
                       SET call_count = call_count + 1,
                           tokens_used = tokens_used + ?,
                           last_used_at = ?,
                           last_used_ip = ?,
                           first_used_at = COALESCE(first_used_at, ?),
                           denied_count = denied_count + ?
                       WHERE key_id = ?""",
                    (int(tokens), now_iso, ip[:64], now_iso,
                     0 if 200 <= int(status) < 400 else 1, key_id),
                )
                self._conn.commit()
        except Exception:  # pragma: no cover - 用量写入不得影响主链路
            pass

    def record_denied(self, key_id: str, *, ip: str = "") -> None:
        """只累加 denied_count —— 配额拒绝不能写明细，否则会延长自己的窗口。"""
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE api_keys SET denied_count = denied_count + 1, last_used_ip = ? "
                    "WHERE key_id = ?",
                    (ip[:64], key_id),
                )
                self._conn.commit()
        except Exception:  # pragma: no cover
            pass

    def quota_check(self, key_id: str, *, window_s: int = 60) -> tuple[bool, int, int | None]:
        """滑动窗口配额检查：返回 (allowed, used, limit)。未设配额视为不限。"""
        record = self.get(key_id)
        limit = record.quota_per_min if record else None
        if not limit or limit <= 0:
            return True, 0, None
        since = time.time() - max(1, int(window_s))
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT COUNT(*) n FROM api_key_usage WHERE key_id = ? AND ts >= ?",
                    (key_id, since),
                ).fetchone()
            used = int(row["n"] if row is not None else 0)
        except Exception:  # pragma: no cover
            return True, 0, limit
        return used < int(limit), used, int(limit)

    def usage(self, key_id: str, *, window_s: int = 86400) -> dict[str, Any]:
        """单把密钥的用量报表（调用量/失败数/延迟/tokens/端点分布/按小时）。"""
        since = time.time() - max(1, int(window_s))
        try:
            with self._lock:
                rows = self._conn.execute(
                    """SELECT ts, endpoint, status, latency_ms, tokens
                       FROM api_key_usage WHERE key_id = ? AND ts >= ?
                       ORDER BY ts DESC""",
                    (key_id, since),
                ).fetchall()
        except Exception as exc:  # pragma: no cover
            return {"key_id": key_id, "window_s": int(window_s), "calls": 0, "error": str(exc)}
        calls = len(rows)
        ok = sum(1 for r in rows if 200 <= int(r["status"]) < 400)
        lat = sorted(float(r["latency_ms"] or 0.0) for r in rows)
        by_endpoint: dict[str, int] = {}
        by_hour: dict[str, int] = {}
        for r in rows:
            ep = str(r["endpoint"] or "")
            by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
            hour = time.strftime("%Y-%m-%dT%H", time.localtime(float(r["ts"])))
            by_hour[hour] = by_hour.get(hour, 0) + 1

        def _pct(q: float) -> float:
            if not lat:
                return 0.0
            idx = min(len(lat) - 1, max(0, int(round(q * (len(lat) - 1)))))
            return round(lat[idx], 1)

        record = self.get(key_id)
        return {
            "key_id": key_id,
            "window_s": int(window_s),
            "owner": record.owner if record else "",
            "consumer": record.consumer if record else "",
            "calls": calls,
            "success": ok,
            "failures": calls - ok,
            "success_rate": round(ok / calls, 3) if calls else 0.0,
            "tokens": sum(int(r["tokens"] or 0) for r in rows),
            "latency_ms": {"avg": round(sum(lat) / len(lat), 1) if lat else 0.0,
                           "p50": _pct(0.5), "p95": _pct(0.95), "max": round(lat[-1], 1) if lat else 0.0},
            "by_endpoint": dict(sorted(by_endpoint.items(), key=lambda kv: -kv[1])[:10]),
            "by_hour": dict(sorted(by_hour.items())),
            "quota": {"limit_per_min": record.quota_per_min if record else None,
                      "used_last_min": self.quota_check(key_id)[1]},
        }

    def usage_overview(self, *, window_s: int = 86400, top: int = 20) -> dict[str, Any]:
        """按密钥聚合的用量总览，用于分派后的使用管理。"""
        since = time.time() - max(1, int(window_s))
        try:
            with self._lock:
                rows = self._conn.execute(
                    """SELECT u.key_id, COUNT(*) calls,
                              SUM(CASE WHEN u.status >= 200 AND u.status < 400 THEN 1 ELSE 0 END) ok,
                              SUM(u.tokens) tokens,
                              AVG(u.latency_ms) avg_latency,
                              MAX(u.ts) last_ts
                       FROM api_key_usage u WHERE u.ts >= ?
                       GROUP BY u.key_id ORDER BY calls DESC LIMIT ?""",
                    (since, int(top)),
                ).fetchall()
        except Exception as exc:  # pragma: no cover
            return {"window_s": int(window_s), "keys": [], "error": str(exc)}
        out = []
        for r in rows:
            rec = self.get(str(r["key_id"]))
            out.append({
                "key_id": r["key_id"],
                "owner": rec.owner if rec else "",
                "consumer": rec.consumer if rec else "",
                "label": rec.label if rec else "",
                "calls": int(r["calls"] or 0),
                "success": int(r["ok"] or 0),
                "tokens": int(r["tokens"] or 0),
                "avg_latency_ms": round(float(r["avg_latency"] or 0.0), 1),
                "last_used_at": _iso(_dt.datetime.fromtimestamp(float(r["last_ts"]), _dt.timezone.utc))
                if r["last_ts"] else None,
            })
        return {"window_s": int(window_s), "keys": out, "total_calls": sum(x["calls"] for x in out)}

    def attention(self, *, expiry_days: int = 14, stale_days: int = 30) -> dict[str, Any]:
        """需要人工关注的密钥：即将过期 / 从未使用 / 已过期未清理。"""
        now = _now()
        soon = now + _dt.timedelta(days=max(0, int(expiry_days)))
        stale_cut = now - _dt.timedelta(days=max(0, int(stale_days)))
        expiring, unused, expired = [], [], []
        for rec in self.list_keys(include_inactive=True):
            if rec.revoked:
                continue
            exp = _parse(rec.expires_at)
            if exp is not None and exp <= now:
                expired.append(rec)
            elif exp is not None and exp <= soon:
                expiring.append(rec)
            last = _parse(rec.last_used_at)
            if rec.call_count == 0 and last is None:
                created = _parse(rec.created_at)
                if created is None or created <= stale_cut:
                    unused.append(rec)
        return {
            "expiring_soon": [r.as_dict() for r in expiring],
            "never_used": [r.as_dict() for r in unused],
            "expired_pending_purge": [r.as_dict() for r in expired],
            "counts": {"expiring_soon": len(expiring), "never_used": len(unused),
                       "expired_pending_purge": len(expired)},
        }

    def dispatch_batch(
        self,
        assignments: list[dict[str, Any]],
        *,
        default_scopes: list[str] | None = None,
        default_ttl_seconds: int | None = None,
        issued_by: str = "",
        channel: str = "",
    ) -> list[dict[str, Any]]:
        """批量分派：一次为多个消费方签发独立密钥（各自作用域/配额/归属）。

        每个元素支持 ``owner`` / ``consumer`` / ``label`` / ``scopes`` /
        ``ttl_seconds`` / ``quota_per_min`` / ``purpose``。
        返回明文仅在本次响应中出现一次。
        """
        out: list[dict[str, Any]] = []
        for item in assignments:
            raw, rec = self.register(
                label=str(item.get("label") or item.get("consumer") or ""),
                scopes=list(item.get("scopes") or default_scopes or ["tasks:execute"]),
                ttl_seconds=item.get("ttl_seconds", default_ttl_seconds),
                owner=str(item.get("owner") or ""),
                consumer=str(item.get("consumer") or ""),
                purpose=str(item.get("purpose") or ""),
                issued_by=issued_by,
                channel=channel,
                quota_per_min=item.get("quota_per_min"),
            )
            out.append({"api_key": raw, "key": rec.as_dict()})
        return out

    def prune_usage(self, *, keep_days: int = 7) -> int:
        """裁掉过期的逐次调用明细（保留聚合计数）。"""
        cutoff = time.time() - max(1, int(keep_days)) * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM api_key_usage WHERE ts < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                (_iso(_now()), key_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def rotate(
        self,
        key_id: str,
        *,
        grace_seconds: int = 0,
        ttl_seconds: int | None = DEFAULT_TTL_SECONDS,
    ) -> tuple[str, APIKeyRecord] | None:
        """Issue a replacement key; retire the old one immediately or after grace."""
        old = self.get(key_id)
        if old is None:
            return None
        raw, new_record = self.register(
            label=old.label,
            scopes=list(old.scopes),
            ttl_seconds=ttl_seconds,
        )
        with self._lock:
            if grace_seconds > 0:
                grace_deadline = _now() + _dt.timedelta(seconds=int(grace_seconds))
                expr = old.expires_at
                existing = _parse(expr)
                if existing is not None and existing < grace_deadline:
                    grace_deadline = existing
                self._conn.execute(
                    "UPDATE api_keys SET expires_at = ? WHERE key_id = ?",
                    (_iso(grace_deadline), key_id),
                )
            else:
                self._conn.execute(
                    "UPDATE api_keys SET revoked_at = ? WHERE key_id = ?",
                    (_iso(_now()), key_id),
                )
            self._conn.execute(
                "UPDATE api_keys SET rotated_from = ? WHERE key_id = ?",
                (key_id, new_record.key_id),
            )
            self._conn.commit()
        rotated = self.get(new_record.key_id)
        return raw, rotated or new_record

    def purge_expired(self, *, older_than_seconds: int = 0) -> int:
        """Delete records expired/revoked longer ago than the grace threshold."""
        cutoff = _now() - _dt.timedelta(seconds=int(older_than_seconds))
        with self._lock:
            cursor = self._conn.execute(
                """DELETE FROM api_keys
                   WHERE (revoked_at IS NOT NULL AND revoked_at < ?)
                      OR (expires_at IS NOT NULL AND expires_at < ?)""",
                (_iso(cutoff), _iso(cutoff)),
            )
            self._conn.commit()
            return cursor.rowcount

    # -- read plane --------------------------------------------------------

    def get(self, key_id: str) -> APIKeyRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_keys(self, *, include_inactive: bool = True) -> list[APIKeyRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        records = [_row_to_record(row) for row in rows]
        if include_inactive:
            return records
        return [rec for rec in records if rec.active]

    def has_keys(self) -> bool:
        """Cheap existence probe used to decide whether auth is required at all."""
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM api_keys LIMIT 1").fetchone()
        return row is not None

    def stats(self) -> dict[str, int]:
        records = self.list_keys()
        return {
            "total": len(records),
            "active": sum(1 for r in records if r.active),
            "expired": sum(1 for r in records if r.expired and not r.revoked),
            "revoked": sum(1 for r in records if r.revoked),
        }


_default_store: APIKeyStore | None = None
_default_lock = threading.RLock()


def get_default_store() -> APIKeyStore:
    """Process-wide lazy singleton (mirrors ``provenance_audit.get_default_layer``)."""
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = APIKeyStore()
    return _default_store


def set_default_store(store: APIKeyStore | None) -> None:
    """Swap the singleton — used by tests and by the admin rotation endpoint."""
    global _default_store
    with _default_lock:
        _default_store = store
