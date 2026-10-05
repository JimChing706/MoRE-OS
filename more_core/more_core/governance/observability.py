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

-- 3. governance_events — 每次 L3 治理评估一行（通过/拦截都记），
--    使"治理拦截率" = blocked / evaluations 自洽可算，无需跨库 join。
CREATE TABLE IF NOT EXISTS governance_events (
    id           TEXT PRIMARY KEY,
    ts           REAL NOT NULL,
    request_id   TEXT NOT NULL DEFAULT '',
    layer        TEXT NOT NULL DEFAULT '',
    task_type    TEXT NOT NULL DEFAULT '',
    blocked      INTEGER NOT NULL DEFAULT 0,
    strict       INTEGER NOT NULL DEFAULT 0,
    rules        TEXT NOT NULL DEFAULT '',   -- JSON list: 触发违规的规则名
    violations   TEXT NOT NULL DEFAULT '',   -- JSON list: 违规消息
    severity     TEXT NOT NULL DEFAULT 'info'
);
CREATE INDEX IF NOT EXISTS idx_gov_ts      ON governance_events(ts);
CREATE INDEX IF NOT EXISTS idx_gov_blocked ON governance_events(blocked);
CREATE INDEX IF NOT EXISTS idx_gov_layer   ON governance_events(layer);

-- 4. council_reviews — 每次 L5 Council 复评一行（高风险/分歧 → 置信度下修）
CREATE TABLE IF NOT EXISTS council_reviews (
    id               TEXT PRIMARY KEY,
    ts               REAL NOT NULL,
    request_id       TEXT NOT NULL DEFAULT '',
    consensus        TEXT NOT NULL DEFAULT '',
    risk_count       INTEGER NOT NULL DEFAULT 0,
    high_risks       INTEGER NOT NULL DEFAULT 0,
    errors           INTEGER NOT NULL DEFAULT 0,
    alignment_before REAL NOT NULL DEFAULT 0,
    adjustment       REAL NOT NULL DEFAULT 0,
    alignment_after  REAL NOT NULL DEFAULT 0,
    downgraded       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_council_ts        ON council_reviews(ts);
CREATE INDEX IF NOT EXISTS idx_council_consensus ON council_reviews(consensus);

-- 5. provider_health_snapshots — 每次 LLM 预检一行（provider 健康 + 兜底链）
CREATE TABLE IF NOT EXISTS provider_health_snapshots (
    id              TEXT PRIMARY KEY,
    ts              REAL NOT NULL,
    ok              INTEGER NOT NULL DEFAULT 0,
    degraded        INTEGER NOT NULL DEFAULT 0,
    n_providers     INTEGER NOT NULL DEFAULT 0,
    n_unhealthy     INTEGER NOT NULL DEFAULT 0,
    n_invalid_model INTEGER NOT NULL DEFAULT 0,
    report          TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_prov_snap_ts ON provider_health_snapshots(ts);
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


def record_governance_event(
    *,
    request_id: str = "",
    layer: str = "L3",
    task_type: str = "",
    blocked: bool = False,
    strict: bool = False,
    rules: Iterable[str] | None = None,
    violations: Iterable[str] | None = None,
) -> None:
    """Append one governance evaluation row (pass *and* block). Never raises.

    Recording passed evaluations too gives the metric a self-contained
    denominator, so ``blocked_rate = blocked / evaluations`` needs no join.
    """
    try:
        conn = _get_conn()
        if conn is None:
            return
        import json

        rule_list = [str(r) for r in (rules or [])]
        viol_list = [str(v) for v in (violations or [])]
        if blocked and "destructive_request_detection" in rule_list:
            severity = "high"
        elif viol_list:
            severity = "warn"
        else:
            severity = "info"
        conn.execute(
            """INSERT INTO governance_events
               (id, ts, request_id, layer, task_type, blocked, strict,
                rules, violations, severity)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                f"gov_{uuid.uuid4().hex[:14]}",
                time.time(),
                request_id or "",
                layer or "",
                task_type or "",
                1 if blocked else 0,
                1 if strict else 0,
                json.dumps(rule_list, ensure_ascii=False)[:2000],
                json.dumps(viol_list, ensure_ascii=False)[:4000],
                severity,
            ),
        )
    except Exception:  # pragma: no cover - defensive
        pass


# 判定"破坏性请求拦截"的规则集合：无论被最前线护栏(ZEN-19)还是 L3 深度
# 规则(destructive_request_detection)拦下，都计入同一指标。
_DESTRUCTIVE_RULES: frozenset[str] = frozenset({
    "destructive_request_detection",
    "zen_19_absolute_prohibition",
})


def _load_json_list(raw: Any) -> list[str]:
    try:
        import json

        val = json.loads(raw or "[]")
        return [str(x) for x in val] if isinstance(val, list) else []
    except Exception:
        return []


def query_governance_stats(window_s: int = 3600) -> dict[str, Any]:
    """Aggregate governance evaluations over the trailing *window_s* seconds.

    Returns a self-contained 拦截率 view::

        evaluations / blocked / violations / passed
        blocked_rate    = blocked / evaluations      (strict 拦截率)
        violation_rate  = violations / evaluations   (违规命中率)
        destructive_blocks / by_rule / by_layer
    """
    empty: dict[str, Any] = {
        "evaluations": 0, "requests": 0, "blocked": 0, "blocked_requests": 0,
        "violations": 0, "passed": 0,
        "blocked_rate": 0.0, "violation_rate": 0.0,
        "destructive_blocks": 0, "by_rule": {}, "by_layer": {},
        "window_s": int(window_s),
    }
    try:
        conn = _get_conn()
        if conn is None:
            return {**empty, "error": "observability store unavailable"}
        conn.row_factory = sqlite3.Row
        since = time.time() - max(0, int(window_s))
        rows = conn.execute(
            """SELECT request_id, layer, task_type, blocked, strict, rules, violations
               FROM governance_events WHERE ts >= ?""",
            (since,),
        ).fetchall()
        if not rows:
            return empty

        by_rule: dict[str, int] = {}
        by_layer: dict[str, int] = {}
        blocked = viol_evals = destructive = 0
        # 拦截率以"请求"（去重 request_id）为口径：同一请求可能经过多个治理
        # 决策点（guardrail / L3），按事件计数会重复放大分母与分子。
        req_ids: set[str] = set()
        blocked_reqs: set[str] = set()
        viol_reqs: set[str] = set()
        for i, r in enumerate(rows):
            rid = r["request_id"] or f"__row_{i}"
            rule_list = _load_json_list(r["rules"])
            viol_list = _load_json_list(r["violations"])
            req_ids.add(rid)
            by_layer[r["layer"] or "unknown"] = by_layer.get(r["layer"] or "unknown", 0) + 1
            if viol_list:
                viol_evals += 1
                viol_reqs.add(rid)
                for name in rule_list:
                    by_rule[name] = by_rule.get(name, 0) + 1
            if int(r["blocked"]):
                blocked += 1
                blocked_reqs.add(rid)
                if _DESTRUCTIVE_RULES & set(rule_list):
                    destructive += 1

        n = len(rows)
        req_total = len(req_ids)
        blocked_req_n = len(blocked_reqs)
        return {
            "evaluations": n,
            "requests": req_total,
            "blocked": blocked,
            "blocked_requests": blocked_req_n,
            "violations": viol_evals,
            "passed": n - viol_evals,
            "blocked_rate": round(blocked_req_n / req_total, 3) if req_total else 0.0,
            "violation_rate": round(len(viol_reqs) / req_total, 3) if req_total else 0.0,
            "destructive_blocks": destructive,
            "by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
            "by_layer": by_layer,
            "window_s": int(window_s),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {**empty, "error": str(exc)}


# 治理告警阈值（可用 evaluate_governance_alerts 的 overrides 覆盖）
_GOV_ALERT_DEFAULTS: dict[str, float] = {
    "min_samples": 10,          # 样本太少不判"率"，避免噪声
    "blocked_rate_warn": 0.30,
    "blocked_rate_crit": 0.60,
    "destructive_blocks_warn": 1,
    "destructive_blocks_crit": 5,
}


def evaluate_governance_alerts(
    stats: dict[str, Any], **overrides: float
) -> list[dict[str, Any]]:
    """Pure threshold evaluation over :func:`query_governance_stats` output.

    Returns ``[{level, code, value, threshold, message}, ...]`` (empty = ok).
    No side effects — callers decide how to surface/dispatch.
    """
    cfg = {**_GOV_ALERT_DEFAULTS, **overrides}
    alerts: list[dict[str, Any]] = []
    n = int(stats.get("requests") or stats.get("evaluations") or 0)
    rate = float(stats.get("blocked_rate") or 0.0)
    destructive = int(stats.get("destructive_blocks") or 0)

    if n >= int(cfg["min_samples"]):
        if rate >= float(cfg["blocked_rate_crit"]):
            alerts.append({
                "level": "critical", "code": "governance_blocked_rate",
                "value": rate, "threshold": float(cfg["blocked_rate_crit"]),
                "message": f"治理拦截率 {rate:.0%} ≥ 临界阈值 {cfg['blocked_rate_crit']:.0%}（样本 {n}）",
            })
        elif rate >= float(cfg["blocked_rate_warn"]):
            alerts.append({
                "level": "warning", "code": "governance_blocked_rate",
                "value": rate, "threshold": float(cfg["blocked_rate_warn"]),
                "message": f"治理拦截率 {rate:.0%} ≥ 告警阈值 {cfg['blocked_rate_warn']:.0%}（样本 {n}）",
            })

    if destructive >= int(cfg["destructive_blocks_crit"]):
        alerts.append({
            "level": "critical", "code": "destructive_request_blocks",
            "value": destructive, "threshold": int(cfg["destructive_blocks_crit"]),
            "message": f"破坏性请求拦截 {destructive} 次 ≥ 临界阈值 {int(cfg['destructive_blocks_crit'])}",
        })
    elif destructive >= int(cfg["destructive_blocks_warn"]):
        alerts.append({
            "level": "warning", "code": "destructive_request_blocks",
            "value": destructive, "threshold": int(cfg["destructive_blocks_warn"]),
            "message": f"破坏性请求拦截 {destructive} 次 ≥ 告警阈值 {int(cfg['destructive_blocks_warn'])}",
        })
    return alerts


def record_council_review(
    *,
    request_id: str = "",
    consensus: str = "",
    risk_count: int = 0,
    high_risks: int = 0,
    errors: int = 0,
    alignment_before: float = 0.0,
    adjustment: float = 0.0,
    alignment_after: float = 0.0,
) -> None:
    """Append one L5 Council-review row (高风险/分歧 → 置信度下修). Never raises."""
    try:
        conn = _get_conn()
        if conn is None:
            return
        conn.execute(
            """INSERT INTO council_reviews
               (id, ts, request_id, consensus, risk_count, high_risks, errors,
                alignment_before, adjustment, alignment_after, downgraded)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"cr_{uuid.uuid4().hex[:14]}",
                time.time(),
                request_id or "",
                consensus or "",
                int(risk_count),
                int(high_risks),
                int(errors),
                float(alignment_before),
                float(adjustment),
                float(alignment_after),
                1 if float(adjustment) < 0 else 0,
            ),
        )
    except Exception:  # pragma: no cover - defensive
        pass


def query_council_stats(window_s: int = 3600) -> dict[str, Any]:
    """Aggregate L5 Council reviews: 下修率 / 共识分布 / 平均调整量。"""
    empty: dict[str, Any] = {
        "reviews": 0, "downgraded": 0, "downgrade_rate": 0.0,
        "divided": 0, "weak": 0, "high_risk_reviews": 0,
        "avg_adjustment": 0.0, "min_adjustment": 0.0,
        "by_consensus": {}, "window_s": int(window_s),
    }
    try:
        conn = _get_conn()
        if conn is None:
            return {**empty, "error": "observability store unavailable"}
        conn.row_factory = sqlite3.Row
        since = time.time() - max(0, int(window_s))
        rows = conn.execute(
            """SELECT consensus, risk_count, high_risks, errors, adjustment, downgraded
               FROM council_reviews WHERE ts >= ?""",
            (since,),
        ).fetchall()
        if not rows:
            return empty

        by_consensus: dict[str, int] = {}
        adjustments: list[float] = []
        downgraded = divided = weak = high_risk = 0
        for r in rows:
            cons = r["consensus"] or "unknown"
            by_consensus[cons] = by_consensus.get(cons, 0) + 1
            adj = float(r["adjustment"] or 0.0)
            adjustments.append(adj)
            if int(r["downgraded"]):
                downgraded += 1
            if cons == "divided":
                divided += 1
            if cons == "weak":
                weak += 1
            if int(r["high_risks"] or 0) > 0:
                high_risk += 1

        n = len(rows)
        return {
            "reviews": n,
            "downgraded": downgraded,
            "downgrade_rate": round(downgraded / n, 3) if n else 0.0,
            "divided": divided,
            "weak": weak,
            "high_risk_reviews": high_risk,
            "avg_adjustment": round(sum(adjustments) / n, 3) if n else 0.0,
            "min_adjustment": round(min(adjustments), 3) if adjustments else 0.0,
            "by_consensus": dict(sorted(by_consensus.items(), key=lambda kv: -kv[1])),
            "window_s": int(window_s),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {**empty, "error": str(exc)}


def record_provider_health(report: dict[str, Any]) -> None:
    """Persist one LLM preflight snapshot (providers + fallback chain). Never raises.

    ``report`` is :meth:`more_core.llm.preflight.LLMPreflight.to_dict` output.
    """
    try:
        conn = _get_conn()
        if conn is None:
            return
        import json

        providers = report.get("providers") or []
        n_unhealthy = sum(1 for p in providers if p.get("healthy") is False)
        n_invalid = sum(1 for p in providers if p.get("model_present") is False)
        # 生效模型（state manager）无效同样计入——这正是"假绿灯"的来源
        if report.get("state_model_present") is False:
            n_invalid += 1
        conn.execute(
            """INSERT INTO provider_health_snapshots
               (id, ts, ok, degraded, n_providers, n_unhealthy, n_invalid_model, report)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                f"ph_{uuid.uuid4().hex[:14]}",
                time.time(),
                1 if report.get("ok") else 0,
                1 if report.get("degraded") else 0,
                len(providers),
                n_unhealthy,
                n_invalid,
                json.dumps(report, ensure_ascii=False)[:20000],
            ),
        )
    except Exception:  # pragma: no cover - defensive
        pass


def query_provider_health(window_s: int = 3600) -> dict[str, Any]:
    """Return the most recent preflight snapshot plus 1h/24h incident counts.

    ``n_invalid_model`` counts providers whose configured model is missing from
    the server's model list — the silent failure that breaks the whole LLM chain.
    """
    empty: dict[str, Any] = {
        "checked_at": 0.0, "ok": None, "degraded": None,
        "providers": [], "chain_declared": [], "chain_registered": [],
        "state_provider": "", "state_model": "", "state_model_present": None,
        "warnings": [], "n_providers": 0, "n_unhealthy": 0,
        "n_invalid_model": 0, "n_inference_failed": 0,
        "snapshots": 0, "window_s": int(window_s),
    }
    try:
        conn = _get_conn()
        if conn is None:
            return {**empty, "error": "observability store unavailable"}
        conn.row_factory = sqlite3.Row
        since = time.time() - max(0, int(window_s))
        rows = conn.execute(
            """SELECT ts, ok, degraded, n_providers, n_unhealthy, n_invalid_model, report
               FROM provider_health_snapshots WHERE ts >= ? ORDER BY ts DESC""",
            (since,),
        ).fetchall()
        if not rows:
            return empty

        import json

        latest = rows[0]
        try:
            report = json.loads(latest["report"] or "{}")
        except Exception:
            report = {}
        providers = report.get("providers") or []
        n_inference_failed = sum(
            1 for pr in providers if pr.get("inference_ok") is False
        )
        return {
            "checked_at": float(latest["ts"]),
            "ok": bool(latest["ok"]),
            "degraded": bool(latest["degraded"]),
            "n_inference_failed": n_inference_failed,
            "providers": providers,
            "chain_declared": report.get("fallback_chain") or [],
            "chain_registered": report.get("chain_registered") or [],
            "state_provider": report.get("state_provider") or "",
            "state_model": report.get("state_model") or "",
            "state_model_present": report.get("state_model_present"),
            "warnings": report.get("warnings") or [],
            "n_providers": int(latest["n_providers"]),
            "n_unhealthy": int(latest["n_unhealthy"]),
            "n_invalid_model": int(latest["n_invalid_model"]),
            "snapshots": len(rows),
            "window_s": int(window_s),
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {**empty, "error": str(exc)}


def evaluate_provider_alerts(health: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure threshold evaluation over :func:`query_provider_health` output.

    Focus: the "silent" config faults that make every LLM call fail —
    invalid model identifier, unhealthy provider, degenerate fallback chain.
    """
    if not health.get("providers") and not health.get("checked_at"):
        return [{
            "level": "warning", "code": "provider_preflight_missing",
            "message": "尚未执行 LLM provider 预检（无健康快照）",
        }]

    alerts: list[dict[str, Any]] = []
    for p in health.get("providers") or []:
        name = p.get("name") or "?"
        if p.get("model_present") is False:
            alerts.append({
                "level": "critical", "code": "provider_invalid_model", "provider": name,
                "message": (
                    f"provider {name} 配置的模型 {p.get('configured_model')!r} 不在服务端模型"
                    f"列表中（可用 {p.get('models_available', 0)} 个）——请求将全部失败"
                ),
            })
        if p.get("healthy") is False:
            alerts.append({
                "level": "critical", "code": "provider_unhealthy", "provider": name,
                "message": f"provider {name} 健康检查失败",
            })
        if p.get("inference_ok") is False:
            alerts.append({
                "level": "critical", "code": "provider_inference_failed", "provider": name,
                "message": (
                    f"provider {name} 推理探针失败（/models 可达但补全失败）——请求会失败"
                ),
            })

    if health.get("state_model_present") is False:
        alerts.append({
            "level": "critical", "code": "state_invalid_model",
            "provider": health.get("state_provider") or "?",
            "message": (
                f"生效模型 {health.get('state_model')!r}"
                f"（provider {health.get('state_provider')!r}）不在服务端模型列表中"
                f"——每次请求都会失败（provider 自身配置可能正确，属配置漂移）"
            ),
        })

    if int(health.get("n_providers") or 0) == 0 and health.get("checked_at"):
        alerts.append({
            "level": "critical", "code": "no_provider_registered",
            "message": "没有任何 LLM provider 注册",
        })
    if health.get("degraded"):
        alerts.append({
            "level": "warning", "code": "fallback_chain_degraded",
            "message": (
                f"兜底链降级：已注册 {health.get('chain_registered')} "
                f"（声明 {health.get('chain_declared')}）"
            ),
        })
    return alerts


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
