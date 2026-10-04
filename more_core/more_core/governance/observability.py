"""Step-4 P0: Cross-runtime observability tables (llm_calls + injection_hits).

Mirrors the BaiLongma Rust chassis' four canonical tables so the two
runtimes can emit into a single ground-truth schema and dashboards can
join against them without translation.  We only ship the two tables that
qnm-os is authoritative for at P0:

  1. ``llm_calls``      — every LLM invocation through LLMManager.generate()
                          (incl. provider, model, latency, tokens, cache hit).
  2. ``injection_hits`` — every L0 policy/evolution injection site:
                            - repair_bias injected into _build_fix_prompt
                            - dynamic_k escalation decided on _candidate_k
                          plus an ``origin`` column so future injectors
                          (silver_habits, chaos, insight) auto-register.

Design rules:
  * WAL-mode SQLite, FK cascade off (keep it intentionally simple — these
    are append-only telemetry tables).
  * All public APIs are ``def record_*(...): try... except: pass``.  They
    NEVER raise, because observability failure must NEVER break the
    user-facing pipeline.
  * Reads use ``query_*`` helpers with sensible ``LIMIT`` defaults and
    ``try/except`` returning ``[]`` on any error.
  * Schema auto-created on first call to ``ensure_schema()`` via the
    singleton ``_INSTANCE`` — no explicit init step required from
    orchestrator boot.
  * Dedupe: ``llm_calls`` has ``UNIQUE(request_id, attempt)`` so retries
    with the same logical request can be grouped by dashboard queries.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id               TEXT PRIMARY KEY,
    ts               REAL NOT NULL,
    request_id       TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 0,
    provider         TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL DEFAULT '',
    temperature      REAL,
    max_tokens       INTEGER,
    prompt_chars     INTEGER NOT NULL DEFAULT 0,
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0,
    success          INTEGER NOT NULL DEFAULT 0,
    cached           INTEGER NOT NULL DEFAULT 0,
    error            TEXT NOT NULL DEFAULT '',
    UNIQUE(request_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts          ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_provider    ON llm_calls(provider, model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_success     ON llm_calls(success);

CREATE TABLE IF NOT EXISTS injection_hits (
    id               TEXT PRIMARY KEY,
    ts               REAL NOT NULL,
    request_id       TEXT NOT NULL DEFAULT '',
    origin           TEXT NOT NULL DEFAULT '',
    injection_site   TEXT NOT NULL DEFAULT '',
    key              TEXT NOT NULL DEFAULT '',
    value_hash       TEXT NOT NULL DEFAULT '',
    applied          INTEGER NOT NULL DEFAULT 1,
    meta             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_inj_ts       ON injection_hits(ts);
CREATE INDEX IF NOT EXISTS idx_inj_origin   ON injection_hits(origin, injection_site);
CREATE INDEX IF NOT EXISTS idx_inj_request  ON injection_hits(request_id);
"""

# Hard cap on db size before we stop appending — telemetry must not eat disk.
_MAX_DB_BYTES = 512 * 1024 * 1024  # 512 MiB


def _sha12(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class _Store:
    """Per-process singleton — module-level, threadsafe access via _lock."""

    path: Path
    conn: sqlite3.Connection | None = None
    ok: bool = False


_INSTANCE: _Store | None = None
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Singleton + schema bootstrap
# ---------------------------------------------------------------------------


def configure(db_path: str | os.PathLike[str]) -> None:
    """(Re)configure the store path.  Idempotent.

    Called by orchestrator boot or Settings reload; future calls close the
    old connection (if any) and let the next record_* call reopen lazily.
    """
    global _INSTANCE
    with _LOCK:
        old = _INSTANCE
        if old is not None and old.conn is not None:
            try:
                old.conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
        _INSTANCE = _Store(path=Path(db_path))


def _ensure(path: Path) -> sqlite3.Connection | None:
    """Open connection + create schema, observing size guard.  Returns None on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _MAX_DB_BYTES:
            # Stop accepting new telemetry.  Existing data is preserved.
            _log.warning("observability db %s over size cap; writes stopped", path)
            return None
        conn = sqlite3.connect(
            str(path),
            isolation_level=None,  # autocommit — writes are tiny individual rows
            check_same_thread=False,
            timeout=1.0,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        return conn
    except Exception as exc:  # pragma: no cover - defensive
        _log.error("observability schema init failed: %s", exc)
        return None


def _get_conn() -> sqlite3.Connection | None:
    """Lazy init — returns usable connection or None.

    Defaults the store path to ``<Settings project_root | cwd>/logs/observability.sqlite``
    on first use; callers that want explicit control use :func:`configure` early.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                from ..core.config import Settings as _S  # local import to avoid circularity

                root = _S().project_root or os.getcwd()
                _INSTANCE = _Store(path=Path(root) / "logs" / "observability.sqlite")
    store = _INSTANCE
    if store.conn is not None:
        return store.conn
    with _LOCK:
        if store.conn is None:
            store.conn = _ensure(store.path)
            store.ok = store.conn is not None
    return store.conn


# ---------------------------------------------------------------------------
# Writes (NEVER raise)
# ---------------------------------------------------------------------------


def record_llm_call(  # noqa: PLR0913 - many cols is intentional here
    *,
    request_id: str,
    provider: str,
    model: str,
    prompt_chars: int,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    success: bool,
    cached: bool = False,
    error: str = "",
    attempt: int = 0,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> None:
    """Append one LLM call row.  Silently no-ops on any failure."""
    try:
        conn = _get_conn()
        if conn is None:
            return
        conn.execute(
            """INSERT OR IGNORE INTO llm_calls
               (id, ts, request_id, attempt, provider, model, temperature,
                max_tokens, prompt_chars, prompt_tokens, completion_tokens,
                latency_ms, success, cached, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"llm_{uuid.uuid4().hex[:14]}",
                time.time(),
                request_id,
                int(attempt),
                provider or "",
                model or "",
                temperature,
                max_tokens,
                int(prompt_chars),
                int(prompt_tokens),
                int(completion_tokens),
                float(latency_ms),
                1 if success else 0,
                1 if cached else 0,
                (error or "")[:4000],
            ),
        )
    except Exception:  # pragma: no cover - defensive
        pass


def record_injection(
    *,
    origin: str,
    injection_site: str,
    key: str = "",
    value_text: str = "",
    applied: bool = True,
    request_id: str = "",
    meta: str | dict[str, Any] | None = None,
) -> None:
    """Append one injection-hit row.  Silently no-ops on any failure.

    Args:
        origin:         subsystem that injected (``evolution_bias``,
                        ``dynamic_k``, ``silver_habit_03``, ...).
        injection_site: where in the pipeline it landed
                        (``l0_build_fix_prompt``, ``l0_candidate_k``, ...).
        key:            short stable identifier (e.g. failure_fp, task_type).
        value_text:     raw content of what was injected — truncated and
                        hashed into ``value_hash``; the full text is never
                        stored (tokens/privacy).
        applied:        True when the injector actually changed output.
        request_id:     owning request id if known.
        meta:           extra dimensions stored as JSON string.
    """
    try:
        conn = _get_conn()
        if conn is None:
            return
        if isinstance(meta, dict):
            import json

            meta_s = json.dumps(meta, ensure_ascii=False)[:2000]
        else:
            meta_s = (str(meta or ""))[:2000]
        value_hash = _sha12(value_text or "")
        conn.execute(
            """INSERT INTO injection_hits
               (id, ts, request_id, origin, injection_site, key, value_hash, applied, meta)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                f"inj_{uuid.uuid4().hex[:14]}",
                time.time(),
                request_id or "",
                origin or "",
                injection_site or "",
                key or "",
                value_hash,
                1 if applied else 0,
                meta_s,
            ),
        )
    except Exception:  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# Reads (return [] / 0 on any failure)
# ---------------------------------------------------------------------------


def query_recent_llm(
    limit: int = 50,
    *,
    provider: str | None = None,
    success: bool | None = None,
) -> list[dict[str, Any]]:
    try:
        conn = _get_conn()
        if conn is None:
            return []
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM llm_calls WHERE 1=1"
        args: list[Any] = []
        if provider:
            sql += " AND provider = ?"
            args.append(provider)
        if success is not None:
            sql += " AND success = ?"
            args.append(1 if success else 0)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        cur = conn.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]
    except Exception:  # pragma: no cover - defensive
        return []


def query_injection_stats(window_s: int = 3600) -> dict[str, int]:
    """Return ``{origin: count}`` aggregated over the last ``window_s`` seconds."""
    try:
        conn = _get_conn()
        if conn is None:
            return {}
        since = time.time() - window_s
        cur = conn.execute(
            "SELECT origin, COUNT(*) n FROM injection_hits WHERE ts >= ? GROUP BY origin",
            (since,),
        )
        return {row[0]: int(row[1]) for row in cur.fetchall()}
    except Exception:  # pragma: no cover - defensive
        return {}


def summary(window_s: int = 3600) -> dict[str, Any]:
    """Aggregate core runtime metrics over the trailing *window_s* seconds.

    Canonical "did the platform actually do work" view: call volume, success
    rate, token consumption and latency percentiles.  Never raises; an
    ``error`` key distinguishes "no data" from "telemetry broken".
    """
    try:
        conn = _get_conn()
        if conn is None:
            return {"samples": 0, "window_s": int(window_s),
                    "error": "observability store unavailable"}
        conn.row_factory = sqlite3.Row
        since = time.time() - max(0, int(window_s))
        rows = conn.execute(
            """SELECT provider, model, success, cached, latency_ms,
                      prompt_tokens, completion_tokens
               FROM llm_calls WHERE ts >= ?""",
            (since,),
        ).fetchall()
        if not rows:
            return {
                "samples": 0, "window_s": int(window_s), "success_rate": 0.0,
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "latency_ms": {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0},
                "providers": {},
            }

        # G2：延迟分位只统计"成功且非缓存"的调用。
        #   * 缓存命中 latency 恒为 0；
        #   * 失败/取消调用（含超时兜底）也以 latency_ms=0 落库。
        # 这两类都会把 p50 拉到 0，掩盖真实延迟分布。
        latencies = sorted(
            float(r["latency_ms"] or 0.0)
            for r in rows
            if not r["cached"] and int(r["success"])
        )
        if not latencies:
            latencies = sorted(
                float(r["latency_ms"] or 0.0) for r in rows if not r["cached"]
            )
        prompt_tok = sum(int(r["prompt_tokens"] or 0) for r in rows)
        completion_tok = sum(int(r["completion_tokens"] or 0) for r in rows)
        ok = sum(1 for r in rows if r["success"])

        def _pct(values: list[float], q: float) -> float:
            if not values:
                return 0.0
            idx = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
            return round(values[idx], 1)

        providers: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = f"{r['provider'] or 'unknown'}:{r['model'] or 'default'}"
            slot = providers.setdefault(
                key, {"calls": 0, "success": 0, "prompt_tokens": 0, "completion_tokens": 0}
            )
            slot["calls"] += 1
            slot["success"] += int(bool(r["success"]))
            slot["prompt_tokens"] += int(r["prompt_tokens"] or 0)
            slot["completion_tokens"] += int(r["completion_tokens"] or 0)
        for slot in providers.values():
            slot["success_rate"] = round(slot["success"] / slot["calls"], 3) if slot["calls"] else 0.0

        return {
            "samples": len(rows),
            "window_s": int(window_s),
            "success_rate": round(ok / len(rows), 3),
            "cached_calls": sum(1 for r in rows if r["cached"]),
            "measured_calls": sum(
                1 for r in rows if not r["cached"] and int(r["success"])
            ),
            "failed_calls": sum(1 for r in rows if not int(r["success"])),
            "tokens": {"prompt": prompt_tok, "completion": completion_tok,
                       "total": prompt_tok + completion_tok},
            "latency_ms": {"avg": round(sum(latencies) / len(latencies), 1),
                           "p50": _pct(latencies, 0.50), "p95": _pct(latencies, 0.95),
                           "max": round(latencies[-1], 1)},
            "providers": providers,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"samples": 0, "window_s": int(window_s), "error": str(exc)}


def close() -> None:
    """Graceful shutdown — not required, but nice for tests."""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None and _INSTANCE.conn is not None:
            try:
                _INSTANCE.conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
            _INSTANCE.conn = None


__all__: Iterable[str] = (
    "configure",
    "record_llm_call",
    "summary",
    "record_injection",
    "query_recent_llm",
    "query_injection_stats",
    "close",
)
