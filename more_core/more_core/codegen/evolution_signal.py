"""Codegen → L2 Evolution signal bridge (P0 · Evolution Feedback Loop).

Persistent structured export of every codegen loop run so L2 can aggregate
*what kinds of fixes actually work* across tasks, instead of discarding all
failure/repair telemetry at task end.

Schema
------
``codegen_runs``       — one row per adjudicate_codegen() call (1:1 with L0 task scopes)
``codegen_failure_modes`` — one row per distinct failure class seen in a run (for L2 query)
``codegen_fix_patterns``  — one row per *successful* repair (for aggregation: "for failure
                        class X, deterministic fix Y succeeded Z% vs LLM-fix W%")

All writes are best-effort / fire-and-forget: a DB error must never break the
user-facing codegen loop.  Path is resolved via Settings.codegen_evolution_db
with a project-root-relative default (``more_core/data/codegen_evolution.db``).

L2 query helpers
----------------
:func:`query_top_fixes_for_failure` — for a given failure fingerprint, return
the (fix_kind, success_rate, sample_count) rows ordered by success rate.  This
is the hook L2's DGM engine will call when it wants to bias its next proposal
toward repair strategies that historically worked.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DB_LOCK = threading.Lock()

_DEFAULT_DB_RELATIVE = "more_core/data/codegen_evolution.db"

FAILURE_CLASS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("syntax_error", re.compile(r"(SyntaxError|IndentationError|TabError|ParseError)")),
    ("import_error", re.compile(r"(ModuleNotFoundError|ImportError)")),
    ("name_error", re.compile(r"NameError")),
    ("type_error", re.compile(r"TypeError")),
    ("attribute_error", re.compile(r"AttributeError")),
    ("key_error_index", re.compile(r"(KeyError|IndexError)")),
    ("assertion_failed", re.compile(r"(AssertionError|assert .* failed)")),
    ("test_failure", re.compile(r"(FAILED|ERROR).*::test_|pytest.*failed|test.*FAIL")),
    ("lint_error", re.compile(r"(ruff[\s:]|flake8[\s:]|mypy[\s:]|eslint[\s:]|tsc[\s:]|E[0-9]{3}|error TS[0-9]{4})", re.IGNORECASE)),
    ("review_p1_p2", re.compile(r"(P1|P2)[^\n]{0,60}(finding|defect|issue|风险|漏洞|缺陷|问题)", re.IGNORECASE)),
    ("safety_blocked", re.compile(r"(safety|dangerous|blocked|violation|拦截|安全)", re.IGNORECASE)),
    ("stagnation", re.compile(r"(stagnant|converged|no progress|stagnation|停滞|收敛)", re.IGNORECASE)),
    ("differential", re.compile(r"(differential|disagreed|差异|不一致)", re.IGNORECASE)),
]


@dataclass(slots=True)
class CodegenRunContext:
    """Task-level metadata handed to the exporter by the caller (L0)."""

    task_id: str = ""
    task_type: str = ""
    query_fingerprint: str = ""
    scope: str = "code"
    project_root: str | None = None
    extra: dict[str, Any] | None = None


# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS codegen_runs (
    run_id          TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL DEFAULT '',
    task_type       TEXT NOT NULL DEFAULT '',
    scope           TEXT NOT NULL DEFAULT 'code',
    query_fp        TEXT NOT NULL DEFAULT '',
    decision        TEXT NOT NULL,                -- pass | partial | escalated
    fix_iterations  INTEGER NOT NULL DEFAULT 0,
    sandbox_ok      INTEGER NOT NULL DEFAULT 0,
    review_state    TEXT,                         -- approved | rejected | NULL
    review_p3       INTEGER NOT NULL DEFAULT 0,
    differential    INTEGER NOT NULL DEFAULT 0,
    stagnant        INTEGER NOT NULL DEFAULT 0,
    blocked         INTEGER NOT NULL DEFAULT 0,
    best_of_k       INTEGER NOT NULL DEFAULT 0,
    assertions_ok   INTEGER NOT NULL DEFAULT 0,
    delegated       INTEGER NOT NULL DEFAULT 0,   -- 1 if chassis/A2A delegation was attempted
    delegation_trigger TEXT NOT NULL DEFAULT '',  -- evolution_escalation | default_gate | user_override
    delegation_state   TEXT NOT NULL DEFAULT '',  -- completed | failed | canceled | '' (if not delegated)
    tier_used       INTEGER NOT NULL DEFAULT -1, -- -1 unknown, 0..3 = T0..T3
    thinking_tokens INTEGER NOT NULL DEFAULT 0,  -- CoT tokens stripped by R2-B (0 for legacy)
    diff_uplift_applied INTEGER NOT NULL DEFAULT 0,  -- 1 if L1 difficulty uplift bias fired
    reasons_json    TEXT NOT NULL DEFAULT '[]',
    checks_json     TEXT NOT NULL DEFAULT '{}',
    artifacts_json  TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_task_type ON codegen_runs(task_type);
CREATE INDEX IF NOT EXISTS idx_runs_decision  ON codegen_runs(decision);
CREATE INDEX IF NOT EXISTS idx_runs_created   ON codegen_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_delegated ON codegen_runs(delegated);

CREATE TABLE IF NOT EXISTS codegen_failure_modes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    failure_class   TEXT NOT NULL,                 -- e.g. import_error, syntax_error
    failure_fp      TEXT NOT NULL,                 -- hash of the failure body
    failure_text    TEXT NOT NULL DEFAULT '',      -- truncated raw error/reason
    iteration       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(run_id) REFERENCES codegen_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_failures_class ON codegen_failure_modes(failure_class);
CREATE INDEX IF NOT EXISTS idx_failures_fp    ON codegen_failure_modes(failure_fp);

CREATE TABLE IF NOT EXISTS codegen_fix_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    failure_class   TEXT NOT NULL,
    failure_fp      TEXT NOT NULL,
    fix_kind        TEXT NOT NULL,                 -- deterministic | llm | review_guided
    iteration       INTEGER NOT NULL DEFAULT 0,
    succeeded       INTEGER NOT NULL DEFAULT 0,    -- 1 = this fix resolved the failure
    fix_hash        TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES codegen_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_fixes_class_kind ON codegen_fix_patterns(failure_class, fix_kind);
CREATE INDEX IF NOT EXISTS idx_fixes_success    ON codegen_fix_patterns(succeeded);
"""


# ── Low-level DB helpers ─────────────────────────────────────────────────────

def _resolve_db_path(project_root: str | None = None) -> Path:
    explicit = os.getenv("MORE_CODEGEN_EVOLUTION_DB")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if project_root:
        base = Path(project_root).resolve()
    else:
        base = Path(__file__).resolve().parents[2]
    return (base / _DEFAULT_DB_RELATIVE).resolve()


def _get_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=2.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Ensure the delegation triad exists BEFORE we run _SCHEMA (SQLite's
    # CREATE TABLE IF NOT EXISTS refuses to add missing columns on an
    # already-existing legacy table, so we must ALTER TABLE first).
    _ensure_schema_migrated(conn)
    with DB_LOCK:
        conn.executescript(_SCHEMA)
    return conn


# ── Fingerprinting helpers ───────────────────────────────────────────────────

def _fingerprint(text: str) -> str:
    """Short stable hash of a failure body; normalises line numbers + paths."""
    if not text:
        return "empty"
    t = re.sub(r'0[xX][0-9a-fA-F]+', 'HEX', text)
    t = re.sub(r'line \d+', 'line N', t)
    t = re.sub(r'File "[^"]+"', 'File "PATH"', t)
    t = re.sub(r'\d+', '0', t)
    t = re.sub(r'\s+', ' ', t).strip().lower()
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]


def classify_failure(text: str) -> tuple[str, str]:
    """Return (failure_class, fingerprint) for an error body / rejection reason."""
    fp = _fingerprint(text)
    if not text:
        return ("unknown", fp)
    for cls, pattern in FAILURE_CLASS_PATTERNS:
        if pattern.search(text):
            return (cls, fp)
    return ("other", fp)


# ── Core export entrypoint ───────────────────────────────────────────────────

def _ensure_schema_migrated(conn: sqlite3.Connection) -> None:
    """Best-effort: ALTER TABLE add any missing delegation columns to old DBs.

    New installations will create all columns via CREATE TABLE IF NOT EXISTS
    above, but existing databases (created before Step-4 Signal+Delegation
    fusion) won't have them.  SQLite's ALTER TABLE is cheap and idempotent via
    ``pragma table_info`` inspection.  Never raises.
    """
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(codegen_runs)").fetchall()}
        needed = {
            "delegated": "INTEGER NOT NULL DEFAULT 0",
            "delegation_trigger": "TEXT NOT NULL DEFAULT ''",
            "delegation_state": "TEXT NOT NULL DEFAULT ''",
            "tier_used": "INTEGER NOT NULL DEFAULT -1",
            "thinking_tokens": "INTEGER NOT NULL DEFAULT 0",
            "diff_uplift_applied": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, ddl in needed.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE codegen_runs ADD COLUMN {col} {ddl}")
        # Old DBs miss the delegated index too; create if absent.
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_runs_delegated'"
        ).fetchall()
        if not idx_rows:
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_delegated ON codegen_runs(delegated)")
            except Exception:
                pass
        conn.commit()
    except Exception:  # pragma: no cover - defensive
        pass


def export_codegen_evolution_signal(
    verdict: Any,
    scratch: dict[str, Any],
    *,
    run_ctx: CodegenRunContext | None = None,
) -> str | None:
    """Persist one codegen verdict + its failure/repair telemetry.

    Returns the generated ``run_id`` on success, ``None`` on any error.
    **Never raises.**
    """
    try:
        ctx = run_ctx or CodegenRunContext()
        db_path = _resolve_db_path(ctx.project_root)
        conn = _get_conn(db_path)
    except Exception as exc:  # pragma: no cover - defensive
        _log.debug("codegen evolution signal: DB init failed: %s", exc)
        return None

    try:
        if hasattr(verdict, "to_dict"):
            v_dict = verdict.to_dict()
        else:
            v_dict = dict(verdict)
    except Exception:
        _log.debug("codegen evolution signal: verdict.to_dict/dict() failed — skipping export")
        return None

    run_id = f"cg_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    decision = str(v_dict.get("decision") or "unknown")
    checks = v_dict.get("checks") or {}
    reasons = v_dict.get("reasons") or []
    artifacts = v_dict.get("artifacts") or {}

    scope = ctx.scope or str(artifacts.get("scope") or "code")

    def _g(key: str, default: Any = None) -> Any:
        return scratch.get(f"{scope}_{key}", default)

    iterations = int(artifacts.get("fix_iterations") or _g("fix_iterations", 0) or 0)
    sandbox_ok = 1 if bool(checks.get("sandbox")) else 0
    review_state = checks.get("review")
    assertions_ok = 1 if bool(checks.get("assertions")) else 0
    review_p3 = 1 if bool(checks.get("review_p3")) else 0
    differential = 1 if bool(checks.get("differential")) else 0
    stagnant = 1 if bool(checks.get("stagnant")) else 0
    blocked = 1 if bool(checks.get("blocked")) else 0
    best_of_k = 1 if bool(artifacts.get("best_of_k") or _g("best_of_k")) else 0

    # ── Step-4 fusion: delegation telemetry ──────────────────────────────
    delegated = 1 if bool(
        scratch.get("_chassis_delegated")
        or artifacts.get("delegated")
        or _g("delegated")
    ) else 0
    trigger = str(
        scratch.get("_chassis_delegation_trigger")
        or artifacts.get("delegation_trigger")
        or _g("delegation_trigger")
        or ""
    )
    del_state = str(
        scratch.get("_chassis_delegation_state")
        or artifacts.get("delegation_state")
        or _g("delegation_state")
        or ""
    )

    # R3 tier/thinking/uplift values — best-effort inference from context or
    # delegation triad (for legacy callers that don't set them explicitly).
    tier_used = scratch.get("tier_used", artifacts.get("tier_used"))
    try:
        tier_used = int(tier_used) if tier_used is not None else -1
    except Exception:
        tier_used = -1
    if tier_used < 0:
        if delegated and trigger == "evolution_escalation":
            tier_used = 0
        elif delegated and trigger == "user_override":
            tier_used = 1
        elif delegated and trigger == "default_gate":
            tier_used = 2
        elif not delegated:
            tier_used = 1
    thinking_tokens = scratch.get("thinking_tokens", artifacts.get("thinking_tokens"))
    try:
        thinking_tokens = max(0, int(thinking_tokens)) if thinking_tokens is not None else 0
    except Exception:
        thinking_tokens = 0
    uplift_from_ctx = bool(
        scratch.get("diff_uplift_applied")
        or artifacts.get("diff_uplift_applied")
    )
    # Rationale string carries "bias-l1-diff-uplift applied" when the
    # difficulty-uplift bias fired; mirror it to the int column.
    uplift_from_str = False
    try:
        for key in ("_bias_applied", "rationale", "advice"):
            val = scratch.get(key) or artifacts.get(key)
            if isinstance(val, str) and "bias-l1-diff-uplift applied" in val:
                uplift_from_str = True
                break
    except Exception:
        pass
    diff_uplift_applied = 1 if (uplift_from_ctx or uplift_from_str) else 0

    # ── Build failure modes from: reasons / review summary / last sbx error ──
    failure_candidates: list[tuple[str, int]] = []  # (text, iteration)
    for reason in reasons:
        if isinstance(reason, str):
            failure_candidates.append((reason, iterations))
    review_summary = artifacts.get("review_summary") or _g("review_summary")
    if review_summary and isinstance(review_summary, str):
        failure_candidates.append((review_summary, iterations))
    sbx = scratch.get("sandbox_result") if scope == "code" else scratch.get("test_result")
    if sbx is not None:
        err = getattr(sbx, "error", None)
        out = getattr(sbx, "output", None)
        combined = ""
        if err:
            combined += str(err)
        if out:
            combined += ("\n" if combined else "") + str(out)
        if combined:
            failure_candidates.append((combined, iterations))

    try:
        # Build artifacts_json *before* entering DB lock so we never hold the
        # lock while doing json.dumps (tiny but safe).
        bias_notes_parts: list[str] = []
        for key in ("_bias_applied", "rationale", "advice"):
            val = scratch.get(key)
            if isinstance(val, str) and val and (
                "delegation-bias applied" in val
                or "bias-l1-diff-uplift applied" in val
            ):
                bias_notes_parts.append(val)
        artifacts_merged: dict[str, Any] = dict(artifacts or {})
        artifacts_merged.update(ctx.extra or {})
        artifacts_merged.update({
            "delegated": bool(delegated),
            "delegation_trigger": trigger,
            "delegation_state": del_state,
            "tier_used": tier_used,
            "thinking_tokens": thinking_tokens,
            "diff_uplift_applied": bool(diff_uplift_applied),
        })
        if bias_notes_parts:
            artifacts_merged["_bias_notes"] = "\n".join(bias_notes_parts)
        artifacts_json_dump = json.dumps(
            artifacts_merged, ensure_ascii=False, default=str,
        )
        reasons_json_dump = json.dumps(reasons, ensure_ascii=False)
        checks_json_dump = json.dumps(checks, ensure_ascii=False, default=str)

        with DB_LOCK:
            _ensure_schema_migrated(conn)
            conn.execute(
                "INSERT INTO codegen_runs ("
                "run_id,task_id,task_type,scope,query_fp,decision,"
                "fix_iterations,sandbox_ok,review_state,review_p3,"
                "differential,stagnant,blocked,best_of_k,assertions_ok,"
                "delegated,delegation_trigger,delegation_state,"
                "tier_used,thinking_tokens,diff_uplift_applied,"
                "reasons_json,checks_json,artifacts_json,created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    ctx.task_id or "",
                    ctx.task_type or "",
                    scope,
                    ctx.query_fingerprint or "",
                    decision,
                    iterations,
                    sandbox_ok,
                    review_state,
                    review_p3,
                    differential,
                    stagnant,
                    blocked,
                    best_of_k,
                    assertions_ok,
                    delegated,
                    trigger,
                    del_state,
                    tier_used,
                    thinking_tokens,
                    diff_uplift_applied,
                    reasons_json_dump,
                    checks_json_dump,
                    artifacts_json_dump,
                    time.time(),
                ),
            )

            seen: set[tuple[str, str]] = set()
            for text, it in failure_candidates:
                cls, fp = classify_failure(text)
                if (cls, fp) in seen:
                    continue
                seen.add((cls, fp))
                conn.execute(
                    "INSERT INTO codegen_failure_modes "
                    "(run_id,failure_class,failure_fp,failure_text,iteration) "
                    "VALUES (?,?,?,?,?)",
                    (run_id, cls, fp, str(text)[:1000], int(it)),
                )

            # ── Fix patterns: map iterations to (failure_class, fix_kind) pairs ──
            if iterations > 0:
                det_repaired_in_run = bool(_g("fix_deterministic"))
                review_guided = bool(_g("review") or _g("review_rejected") or _g("review_approved"))
                succeeded_all = 1 if decision == "pass" else 0
                for (cls, fp) in seen:
                    if det_repaired_in_run:
                        conn.execute(
                            "INSERT INTO codegen_fix_patterns "
                            "(run_id,failure_class,failure_fp,fix_kind,iteration,succeeded,fix_hash) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (run_id, cls, fp, "deterministic", 1, succeeded_all, fp),
                        )
                    if review_guided:
                        conn.execute(
                            "INSERT INTO codegen_fix_patterns "
                            "(run_id,failure_class,failure_fp,fix_kind,iteration,succeeded,fix_hash) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (run_id, cls, fp, "review_guided", iterations, succeeded_all, fp),
                        )
                    conn.execute(
                        "INSERT INTO codegen_fix_patterns "
                        "(run_id,failure_class,failure_fp,fix_kind,iteration,succeeded,fix_hash) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (run_id, cls, fp, "llm", iterations, succeeded_all, fp),
                    )
            conn.commit()
    except Exception as exc:  # pragma: no cover - defensive, must not break callers
        try:
            conn.rollback()
        except Exception:
            pass
        _log.debug("codegen evolution signal: insert failed: %s", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return run_id


# ── L2-facing query API ──────────────────────────────────────────────────────

def query_top_fixes_for_failure(
    failure_class: str,
    *,
    min_samples: int = 3,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate successful-fix rates for a given failure class.

    Returned rows are ordered by success rate descending::

        [
          {"fix_kind": "deterministic", "success_rate": 0.82, "samples": 45, "failures": 37},
          {"fix_kind": "llm",           "success_rate": 0.51, "samples": 120, "failures": 103},
          ...
        ]

    L2 DGM's next variant proposal will be able to bias the fix strategy
    toward the top entry, closing the "cold start every time" gap described
    in the Step-2 plan.
    """
    try:
        db_path = _resolve_db_path(project_root)
        conn = _get_conn(db_path)
    except Exception as exc:  # pragma: no cover
        _log.debug("query_top_fixes: DB init failed: %s", exc)
        return []
    try:
        rows = conn.execute(
            """
            SELECT fix_kind,
                   COUNT(*)                                     AS total,
                   SUM(succeeded)                               AS successes,
                   COUNT(DISTINCT failure_fp)                   AS distinct_failures
            FROM   codegen_fix_patterns
            WHERE  failure_class = ?
            GROUP  BY fix_kind
            HAVING COUNT(*) >= ?
            ORDER  BY (CAST(SUM(succeeded) AS REAL) / COUNT(*)) DESC, total DESC
            """,
            (failure_class, min_samples),
        ).fetchall()
    except Exception as exc:
        _log.debug("query_top_fixes: query failed: %s", exc)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    out: list[dict[str, Any]] = []
    for fix_kind, total, successes, distinct in rows:
        total = int(total or 0)
        successes = int(successes or 0)
        rate = (successes / total) if total else 0.0
        out.append(
            {
                "fix_kind": fix_kind,
                "success_rate": round(rate, 4),
                "samples": total,
                "successful_samples": successes,
                "distinct_failures": int(distinct or 0),
            }
        )
    return out


def query_verdict_stats(
    *,
    task_type: str | None = None,
    last_n_days: int | None = 7,
    project_root: str | None = None,
) -> dict[str, Any]:
    """High-level run-aggregation stats returned by the /api/v1/evolution endpoint.

    Returns counts + pass rate by decision, total distinct failure fingerprints
    seen in the window, and best fix-kind per top failure class.
    """
    try:
        db_path = _resolve_db_path(project_root)
        conn = _get_conn(db_path)
    except Exception as exc:  # pragma: no cover
        _log.debug("query_verdict_stats: DB init failed: %s", exc)
        return {}
    try:
        q = "SELECT decision, COUNT(*) FROM codegen_runs"
        params: list[Any] = []
        where: list[str] = []
        if task_type:
            where.append("task_type = ?")
            params.append(task_type)
        if last_n_days:
            where.append("created_at >= ?")
            params.append(time.time() - last_n_days * 86400)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " GROUP BY decision"
        rows = conn.execute(q, params).fetchall()
        by_decision = {d: int(c or 0) for d, c in rows}
        total = sum(by_decision.values())
        top_failures = conn.execute(
            "SELECT failure_class, COUNT(DISTINCT failure_fp) AS distinct_fps, "
            "       COUNT(*) AS occurrences "
            "FROM codegen_failure_modes "
            "GROUP BY failure_class ORDER BY occurrences DESC LIMIT 8"
        ).fetchall()
    except Exception as exc:
        _log.debug("query_verdict_stats: query failed: %s", exc)
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {
        "total_runs": total,
        "by_decision": by_decision,
        "pass_rate": round((by_decision.get("pass", 0) / total), 4) if total else 0.0,
        "top_failure_classes": [
            {
                "failure_class": fc,
                "distinct_fingerprints": int(dfp),
                "occurrences": int(occ),
                "top_fixes": query_top_fixes_for_failure(fc, min_samples=1, project_root=project_root)[:3],
            }
            for fc, dfp, occ in top_failures
        ],
    }


# ── L0-facing loopback bias helpers (Step-2+ · self-evolution feedback) ────


def get_repair_bias_for_failure(
    failure_text: str,
    *,
    min_samples: int = 3,
    project_root: str | None = None,
) -> str:
    """Return a short natural-language directive to inject into the fix prompt.

    The directive summarises *which repair strategy historically resolved
    failures similar to this one most often*, so L0's next fix attempt is
    biased toward the winning strategy rather than starting cold every time.

    Returns an empty string when the signal is absent / too noisy (``<
    min_samples``) so callers can skip injection.  Never raises.
    """
    try:
        cls, fp = classify_failure(failure_text or "")
        # Query first by exact fingerprint; if too few samples, fall back to
        # the broader class.  Signal uses the fingerprint bucket for
        # precision, class bucket for recall.
        rows_fp: list[dict[str, Any]] = []
        try:
            db_path = _resolve_db_path(project_root)
            conn = _get_conn(db_path)
        except Exception:
            return ""
        try:
            fp_rows = conn.execute(
                """
                SELECT fix_kind, COUNT(*), SUM(succeeded)
                FROM   codegen_fix_patterns
                WHERE  failure_fp = ?
                GROUP  BY fix_kind
                HAVING COUNT(*) >= ?
                ORDER  BY (CAST(SUM(succeeded) AS REAL) / COUNT(*)) DESC, COUNT(*) DESC
                """,
                (fp, max(2, min_samples - 1)),
            ).fetchall()
            rows_fp = [
                {
                    "fix_kind": kind,
                    "success_rate": (s / n) if n else 0.0,
                    "samples": int(n or 0),
                }
                for kind, n, s in fp_rows
            ]
        except Exception:
            rows_fp = []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        signal = rows_fp[0] if rows_fp else None
        if signal is None:
            class_rows = query_top_fixes_for_failure(
                cls, min_samples=min_samples, project_root=project_root
            )
            if class_rows:
                signal = class_rows[0]

        if not signal:
            return ""

        rate_pct = int(round(float(signal["success_rate"]) * 100))
        samples = int(signal.get("samples") or 0)
        kind_label = {
            "deterministic": "确定性修复（语法/导入/缩进层，零 LLM 开销）",
            "review_guided": "按评审结论定向修复（不要重做完整代码，只修评审点）",
            "llm": "LLM 全量重写（结合 sandbox 错误信息逐行定位）",
        }.get(str(signal["fix_kind"]), f"修复策略={signal['fix_kind']}")

        # Build CJK/English bilingual directive so prompts in either language
        # pick up the signal cleanly.
        zh = (
            f"【进化信号】历史同类错误（{cls}）共 {samples} 次记录："
            f"用「{kind_label}」成功率 {rate_pct}%，优先采用该策略。"
        )
        en = (
            f"[Evolution signal] Historical {cls} failures (n={samples}): "
            f"strategy '{signal['fix_kind']}' succeeded {rate_pct}%. "
            f"Prefer that strategy before anything else."
        )
        return f"{zh}\n{en}"
    except Exception:
        return ""


def query_dynamic_k(
    *,
    task_type: str = "",
    query_fp: str = "",
    min_runs: int = 5,
    escalate_threshold: float = 0.55,
    project_root: str | None = None,
) -> tuple[int, str]:
    """Auto-upgrade best-of-k for task categories that historically struggle.

    Decision policy:
      * **No signal (< min_runs)**                → k=0 (fallback to caller default) + empty rationale.
      * **Pass rate at or above threshold**        → k=0 (single-generation baseline is fine).
      * **Pass rate *below* threshold**            → k=2 (force best-of-2 + differential)
        + a short human-readable rationale string suitable for scratch["_l0_k_rationale"].

    Rationale is always returned; if escalation is disabled the string
    explains *why* k was not bumped (useful for audit trail).
    """
    k = 0
    rationale = ""
    try:
        db_path = _resolve_db_path(project_root)
        conn = _get_conn(db_path)
    except Exception:
        return k, rationale
    try:
        params: list[Any] = []
        where: list[str] = []
        if task_type:
            where.append("task_type = ?")
            params.append(task_type)
        if query_fp:
            where.append("query_fp = ?")
            params.append(query_fp)
        q = (
            "SELECT COUNT(*), SUM(CASE WHEN decision = 'pass' THEN 1 ELSE 0 END) "
            "FROM codegen_runs"
        )
        if where:
            q += " WHERE " + " AND ".join(where)
        (total, passed) = conn.execute(q, params).fetchone()
        total = int(total or 0)
        passed = int(passed or 0)
        if total < min_runs:
            rationale = (
                f"dynamic-k: not enough history (n={total} < {min_runs}); "
                f"use default k policy."
            )
            return 0, rationale
        rate = passed / total if total else 0.0
        if rate >= escalate_threshold:
            rationale = (
                f"dynamic-k: pass rate {rate:.0%} >= threshold "
                f"{escalate_threshold:.0%}; single-gen baseline OK (n={total})."
            )
            return 0, rationale
        k = 2
        rationale = (
            f"dynamic-k: task_type={task_type or 'any'} pass rate {rate:.0%} "
            f"< {escalate_threshold:.0%} (n={total}); escalating to best-of-2 "
            f"for reliability."
        )
    except Exception:
        return 0, ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return k, rationale


# ── Linkage-2 (LC2): delegation success statistics + bias ──────────────────

# Minimum samples per bucket before we trust delegation-bias statistics.
_DELEGATION_BIAS_MIN_SAMPLES = 30
# Minimum absolute uplift (Δ percentage points) required to relax the
# escalation threshold.  0.05 = 5pp.
_DELEGATION_BIAS_MIN_UPLIFT = 0.05
# Max escalation threshold after bias — prevents runaway threshold inflation.
_DELEGATION_BIAS_MAX_THRESHOLD = 0.75
# Threshold relaxation delta once chassis delegation proves superior.
_DELEGATION_BIAS_THRESHOLD_STEP = 0.10


def get_delegation_success_stats(
    *,
    task_type: str = "",
    query_fp: str = "",
    project_root: str | None = None,
    min_samples: int = _DELEGATION_BIAS_MIN_SAMPLES,
) -> dict[str, dict[str, float]]:
    """Return pass-rate buckets keyed by delegation strategy.

    Buckets:
      * ``local`` – runs that never delegated (delegated=0).
        Baseline local-only policy.
      * ``chassis_default`` – delegated=1 + trigger='default_gate'.
      * ``chassis_evolution`` – delegated=1 + trigger='evolution_escalation'.
        The specific bucket the bias logic primarily cares about.

    Each bucket value is ``{"n": int, "passed": int, "rate": float[0,1]}``.
    Empty buckets return ``{"n": 0, "passed": 0, "rate": 0.0}``.

    Never raises; returns empty dict shape on error / DB missing.
    """
    empty_bucket = {"n": 0, "passed": 0, "rate": 0.0}
    result: dict[str, dict[str, float]] = {
        "local": dict(empty_bucket),
        "chassis_default": dict(empty_bucket),
        "chassis_evolution": dict(empty_bucket),
    }
    try:
        db_path = _resolve_db_path(project_root)
        conn = _get_conn(db_path)
    except Exception:
        return result
    try:
        where: list[str] = []
        params: list[Any] = []
        if task_type:
            where.append("task_type = ?")
            params.append(task_type)
        if query_fp:
            where.append("query_fp = ?")
            params.append(query_fp)
        filter_suffix = (
            (" WHERE " + " AND ".join(where)) if where else ""
        )
        # Three separate queries (cheap, indexed via idx_runs_delegated for
        # chassis buckets; and avoids complex CASE bloat).
        queries: list[tuple[str, str]] = [
            (
                "local",
                "SELECT COUNT(*), SUM(CASE WHEN decision='pass' THEN 1 ELSE 0 END) "
                "FROM codegen_runs"
                f"{filter_suffix + (' AND ' if where else ' WHERE ')}delegated = 0",
            ),
            (
                "chassis_default",
                "SELECT COUNT(*), SUM(CASE WHEN decision='pass' AND delegation_state='completed' THEN 1 ELSE 0 END) "
                "FROM codegen_runs"
                f"{filter_suffix + (' AND ' if where else ' WHERE ')}delegated = 1 AND delegation_trigger = 'default_gate'",
            ),
            (
                "chassis_evolution",
                "SELECT COUNT(*), SUM(CASE WHEN decision='pass' AND delegation_state='completed' THEN 1 ELSE 0 END) "
                "FROM codegen_runs"
                f"{filter_suffix + (' AND ' if where else ' WHERE ')}delegated = 1 AND delegation_trigger = 'evolution_escalation'",
            ),
        ]
        # Re-bind params per query since the suffix changes placeholder order.
        for key, q_text in queries:
            # Rebuild with per-bucket where clause and then append the
            # delegated/trigger parts; simpler approach: re-build from a
            # shared base per query via positional args concat so parameter
            # order matches the query text exactly.
            parts = q_text.split(" WHERE ", 1)
            # Reconstruct query from task_type/query_fp + bucket predicates.
            shared_where: list[str] = []
            shared_params: list[Any] = []
            if task_type:
                shared_where.append("task_type = ?")
                shared_params.append(task_type)
            if query_fp:
                shared_where.append("query_fp = ?")
                shared_params.append(query_fp)
            if key == "local":
                bucket_filter = "delegated = 0"
                passed_expr = "decision='pass'"
            else:
                if key == "chassis_default":
                    trigger_expr = "delegation_trigger = 'default_gate'"
                else:
                    trigger_expr = "delegation_trigger = 'evolution_escalation'"
                bucket_filter = f"delegated = 1 AND {trigger_expr}"
                passed_expr = "decision='pass' AND delegation_state='completed'"
            full_where_parts = shared_where + [bucket_filter]
            final_q = (
                f"SELECT COUNT(*), SUM(CASE WHEN {passed_expr} THEN 1 ELSE 0 END) "
                "FROM codegen_runs WHERE " + " AND ".join(full_where_parts)
            )
            row = conn.execute(final_q, shared_params).fetchone()
            n = int(row[0] or 0)
            passed = int(row[1] or 0)
            rate = (passed / n) if n >= min_samples else 0.0
            result[key] = {
                "n": float(n),
                "passed": float(passed),
                "rate": rate if n >= min_samples else 0.0,
            }
    except Exception:
        # Never raise — bias is an opportunistic optimisation, not a hard dependency.
        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return result


def _delegation_bias_for_query(
    *,
    task_type: str,
    query_fp: str,
    escalate_threshold: float,
    project_root: str | None,
) -> tuple[float | None, str]:
    """Determine whether chassis delegation success statistically justifies
    relaxing the escalation threshold in :func:`query_dynamic_k`.

    Returns ``(adjusted_threshold_or_None, rationale_suffix)`` – ``None``
    means no bias applies; a non-None float replaces the caller's
    ``escalate_threshold`` with a more permissive (higher) value so that
    more tasks get routed to the chassis early.

    Bias conditions (ALL must hold):
      * local bucket n ≥ min_samples
      * chassis_evolution bucket n ≥ min_samples
      * chassis_evolution rate ≥ 5pp above local rate (per
        _DELEGATION_BIAS_MIN_UPLIFT)
      * adjusted threshold ≤ _DELEGATION_BIAS_MAX_THRESHOLD
    """
    stats = get_delegation_success_stats(
        task_type=task_type,
        query_fp=query_fp,
        project_root=project_root,
    )
    local = stats["local"]
    evol = stats["chassis_evolution"]
    if local["n"] < _DELEGATION_BIAS_MIN_SAMPLES or evol["n"] < _DELEGATION_BIAS_MIN_SAMPLES:
        return None, ""
    delta = evol["rate"] - local["rate"]
    if delta < _DELEGATION_BIAS_MIN_UPLIFT:
        return None, (
            f"delegation-bias: chassis evolution {evol['rate']:.0%} vs "
            f"local {local['rate']:.0%} (Δ={delta:+.0%} < "
            f"{_DELEGATION_BIAS_MIN_UPLIFT:.0%} uplift; no threshold relax)."
        )
    adjusted = min(
        escalate_threshold + _DELEGATION_BIAS_THRESHOLD_STEP,
        _DELEGATION_BIAS_MAX_THRESHOLD,
    )
    suffix = (
        f"delegation-bias: chassis_evolution {evol['rate']:.0%} n={int(evol['n'])} "
        f"> local {local['rate']:.0%} n={int(local['n'])} (Δ={delta:+.0%}); "
        f"threshold {escalate_threshold:.0%} → {adjusted:.0%} "
        f"(trust chassis +0.1 step). "
        f"delegation-bias applied. "
        f"bias-l1-diff-uplift applied (escalation threshold raised)."
    )
    return adjusted, suffix


def query_dynamic_k_with_delegation_bias(
    *,
    task_type: str = "",
    query_fp: str = "",
    min_runs: int = 5,
    escalate_threshold: float = 0.55,
    project_root: str | None = None,
) -> tuple[int, str]:
    """Extended version of :func:`query_dynamic_k` that opportunistically
    applies the Linkage-2 delegation-success bias.

    Semantics are identical to ``query_dynamic_k``.  When the historical
    chassis-evolution bucket (trigger=evolution_escalation) demonstrates a
    statistically meaningful uplift over the local-only baseline AND has
    sufficient samples (≥ :data:`_DELEGATION_BIAS_MIN_SAMPLES`), the
    escalation threshold is relaxed upward by
    :data:`_DELEGATION_BIAS_THRESHOLD_STEP` (clamped to
    :data:`_DELEGATION_BIAS_MAX_THRESHOLD`).  Relaxing the threshold makes
    it *easier* to trigger a dynamic-k upgrade, which in turn makes the
    L0 delegation advice more likely to pick chassis delegation (see
    ``_evolution_delegation_advice`` in l0_execution.py) creating a positive
    feedback loop: the better chassis delegation performs, the more often
    we let it try, thus generating more data that further refines the bias.

    If any error occurs during bias computation, the original
    ``query_dynamic_k`` result is returned unchanged — never raises.
    """
    # First pass: vanilla dynamic-k without bias (so we always get a baseline
    # result even if the DB / bias code misbehaves).
    base_k, base_rationale = query_dynamic_k(
        task_type=task_type,
        query_fp=query_fp,
        min_runs=min_runs,
        escalate_threshold=escalate_threshold,
        project_root=project_root,
    )
    try:
        adjusted, bias_suffix = _delegation_bias_for_query(
            task_type=task_type,
            query_fp=query_fp,
            escalate_threshold=escalate_threshold,
            project_root=project_root,
        )
        if adjusted is None:
            # No bias applies; optionally append the no-go rationale so
            # downstream tooling can surface *why* bias skipped.
            if bias_suffix:
                combined = base_rationale + (" " if base_rationale else "") + bias_suffix
                return base_k, combined
            return base_k, base_rationale
        # Bias applied: re-run dynamic-k with the relaxed threshold so the
        # k decision AND the rationale text both reflect the new threshold.
        biased_k, biased_rationale = query_dynamic_k(
            task_type=task_type,
            query_fp=query_fp,
            min_runs=min_runs,
            escalate_threshold=adjusted,
            project_root=project_root,
        )
        # Always append the bias suffix so downstream audit can tell this
        # decision was influenced by delegation history.
        suffix = (
            f" [delegation-bias applied: Δthreshold=+{adjusted - escalate_threshold:.0%};"
            f" source=evolution_escalation historical uplift]"
        )
        final_rationale = biased_rationale + suffix
        return biased_k, final_rationale
    except Exception:
        # Never fail — bias is best-effort.
        return base_k, base_rationale


# ── Evolution summary for monitoring / dashboard ──────────────────────────


def compute_evolution_summary(
    *,
    task_type: str = "",
    query_fp: str = "",
    project_root: str | None = None,
) -> dict:
    """Snapshot statistics for the evolution signal dashboard.

    Shape::

        {
          "total_runs": int,
          "passed_runs": int,
          "overall_pass_rate": float,
          "decision_hist":   {pass|partial|escalated: int},
          "trigger_hist":    {"", evolution_escalation, default_gate, user_override: int},
          "strategy_rates":  {"local"/"chassis_default"/"chassis_evolution":
                                {"n"/"passed"/"rate": float}},
          "bias_applied_count": int,  # runs whose artifacts_json claim bias applied
          "top_task_types":  [(task_type_str, count), ...] top 10,
          "range": {"min_created_at": float|None, "max_created_at": float|None}
        }

    Always returns a dict with the keys above; on DB error / missing DB the
    numeric values are zeroed out and lists are empty (never raises).
    """
    empty_strategy = {"n": 0.0, "passed": 0.0, "rate": 0.0}
    _tier_empty = {
        "n": 0, "passed": 0, "pass_rate": 0.0,
        "avg_thinking_ratio": 0.0, "tier_transitions_per_hour": 0.0,
    }
    result: dict = {
        "total_runs": 0,
        "passed_runs": 0,
        "overall_pass_rate": 0.0,
        "decision_hist": {"pass": 0, "partial": 0, "escalated": 0},
        "trigger_hist": {"": 0, "evolution_escalation": 0, "default_gate": 0, "user_override": 0},
        "strategy_rates": {
            "local": dict(empty_strategy),
            "chassis_default": dict(empty_strategy),
            "chassis_evolution": dict(empty_strategy),
        },
        "tier_breakdown": {
            "T0": dict(_tier_empty),
            "T1": dict(_tier_empty),
            "T2": dict(_tier_empty),
            "T3": dict(_tier_empty),
        },
        "bias_applied_count": 0,
        "bias_l1_diff_uplift_count": 0,
        "bias_l1_diff_uplift_aligned": True,
        "top_task_types": [],
        "range": {"min_created_at": None, "max_created_at": None},
    }
    try:
        db_path = _resolve_db_path(project_root)
        conn = _get_conn(db_path)
    except Exception:
        return result
    try:
        where_parts: list[str] = []
        where_params: list = []
        if task_type:
            where_parts.append("task_type = ?")
            where_params.append(task_type)
        if query_fp:
            where_parts.append("query_fp = ?")
            where_params.append(query_fp)
        where_suffix = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # 1) Totals / rate / range
        row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN decision='pass' THEN 1 ELSE 0 END), "
            "       MIN(created_at), MAX(created_at) FROM codegen_runs "
            + where_suffix,
            where_params,
        ).fetchone()
        total = int(row[0] or 0)
        passed = int(row[1] or 0)
        result["total_runs"] = total
        result["passed_runs"] = passed
        result["overall_pass_rate"] = (passed / total) if total else 0.0
        result["range"]["min_created_at"] = row[2] if row[2] is not None else None
        result["range"]["max_created_at"] = row[3] if row[3] is not None else None

        # 2) Decision histogram
        q_dec = "SELECT decision, COUNT(*) FROM codegen_runs"
        if where_parts:
            q_dec += " WHERE " + " AND ".join(where_parts)
        q_dec += " GROUP BY decision"
        for decision, count in conn.execute(q_dec, where_params).fetchall():
            if decision in result["decision_hist"]:
                result["decision_hist"][decision] = int(count)

        # 3) Delegation trigger histogram
        q_trig = "SELECT delegation_trigger, COUNT(*) FROM codegen_runs"
        if where_parts:
            q_trig += " WHERE " + " AND ".join(where_parts)
        q_trig += " GROUP BY delegation_trigger"
        for trigger, count in conn.execute(q_trig, where_params).fetchall():
            # default-gate/user-override/evolution_escalation/"" or other
            if trigger in result["trigger_hist"]:
                result["trigger_hist"][trigger] = int(count)
            else:
                result["trigger_hist"][str(trigger)] = int(count)

        # 4) Bias-applied count (artifacts_json carries the applied tag, or
        # rationale artifacts_json._bias_applied was set if caller injected)
        q_bias = (
            "SELECT COUNT(*) FROM codegen_runs"
            + ((" WHERE " + " AND ".join(where_parts + ["artifacts_json LIKE ?"]))
               if where_parts else
               " WHERE artifacts_json LIKE ?")
        )
        bias_params = where_params + ["%delegation-bias applied%"]
        (bias_count,) = conn.execute(q_bias, bias_params).fetchone()
        result["bias_applied_count"] = int(bias_count or 0)

        # 5) Top task types (top 10)
        q_tt = "SELECT task_type, COUNT(*) AS c FROM codegen_runs"
        if where_parts:
            q_tt += " WHERE " + " AND ".join(where_parts)
        q_tt += " GROUP BY task_type ORDER BY c DESC LIMIT 10"
        result["top_task_types"] = [
            (str(tt), int(c)) for tt, c in conn.execute(q_tt, where_params).fetchall()
        ]

        # 5.5) R3 Tier breakdown — T0..T3 per-tier n / passed / pass_rate /
        # avg_thinking_ratio / tier_transitions_per_hour.  Legacy rows with
        # tier_used == -1 are re-bucketed via delegation triad.
        tb = {f"T{i}": dict(_tier_empty) for i in range(4)}
        _tier_thinking_defaults = (0.55, 0.20, 0.02, 0.0)
        tb_thinking_sum: dict[int, float] = {i: 0.0 for i in range(4)}
        tb_thinking_n: dict[int, int] = {i: 0 for i in range(4)}
        transitions_count = 0
        ts_list: list[float] = []
        tier_seq: list[int] = []
        q_tb = (
            "SELECT tier_used, decision, thinking_tokens, "
            "       delegated, delegation_trigger, created_at FROM codegen_runs"
        )
        if where_parts:
            q_tb += " WHERE " + " AND ".join(where_parts)
        q_tb += " ORDER BY created_at"
        for tier_raw, decision, think_tok, deleg, trig, ts in conn.execute(
            q_tb, where_params
        ).fetchall():
            try:
                tier_i = int(tier_raw) if tier_raw is not None else -1
            except Exception:
                tier_i = -1
            # Legacy re-bucket (mirrors the INSERT logic above).
            if tier_i not in (0, 1, 2, 3):
                if deleg and str(trig) == "evolution_escalation":
                    tier_i = 0
                elif deleg and str(trig) == "user_override":
                    tier_i = 1
                elif deleg and str(trig) == "default_gate":
                    tier_i = 2
                elif not deleg:
                    tier_i = 1
                else:
                    tier_i = 3  # anything else → fallback tier
            key = f"T{tier_i}"
            tb[key]["n"] += 1
            if str(decision) == "pass":
                tb[key]["passed"] += 1
            # avg_thinking_ratio — prefer actual to tier-default heuristic
            try:
                tt = max(0, int(think_tok or 0))
            except Exception:
                tt = 0
            if tt > 0:
                ratio = tt / (tt + 128.0)  # ~ answer heuristic
            else:
                ratio = _tier_thinking_defaults[tier_i]
            tb_thinking_sum[tier_i] += ratio
            tb_thinking_n[tier_i] += 1
            if ts is not None:
                ts_list.append(float(ts))
            tier_seq.append(tier_i)

        # pass_rate + avg_thinking_ratio per bucket
        for i, key in enumerate(tb):
            n = tb[key]["n"]
            tb[key]["pass_rate"] = (tb[key]["passed"] / n) if n else 0.0
            tn = tb_thinking_n[i]
            tb[key]["avg_thinking_ratio"] = (
                (tb_thinking_sum[i] / tn) if tn else _tier_thinking_defaults[i]
            )
        # tier_transitions_per_hour (shared single value, broadcast to all buckets
        # so dashboards can display it at T0 without needing a special key)
        if len(tier_seq) >= 2:
            for a, b in zip(tier_seq, tier_seq[1:]):
                if a != b:
                    transitions_count += 1
        span_h = (
            max((max(ts_list) - min(ts_list)) / 3600.0, 1.0 / 3600.0)
            if len(ts_list) >= 2
            else 1.0
        )
        tph = transitions_count / max(span_h, 1.0 / 3600.0)
        for key in tb:
            tb[key]["tier_transitions_per_hour"] = round(tph, 3)
        result["tier_breakdown"] = tb

        # 5.6) R3 L1 diff-uplift bias count + two-way alignment with the
        # existing delegation-bias count.  Sum the dedicated column first;
        # fall back to a substring search for legacy DBs where the column
        # exists but writes only carried the string tag.
        q_uplift_sum = "SELECT SUM(diff_uplift_applied) FROM codegen_runs"
        if where_parts:
            q_uplift_sum += " WHERE " + " AND ".join(where_parts)
        (uplift_sum_row,) = conn.execute(q_uplift_sum, where_params).fetchone()
        uplift_count = int(uplift_sum_row or 0)
        if uplift_count == 0:
            q_uplift_str = (
                "SELECT COUNT(*) FROM codegen_runs"
                + (
                    (" WHERE " + " AND ".join(where_parts + ["artifacts_json LIKE ?"]))
                    if where_parts
                    else " WHERE artifacts_json LIKE ?"
                )
            )
            uplift_params = where_params + ["%bias-l1-diff-uplift applied%"]
            (uplift_count_row,) = conn.execute(q_uplift_str, uplift_params).fetchone()
            uplift_count = int(uplift_count_row or 0)
        result["bias_l1_diff_uplift_count"] = uplift_count
        bac = int(result.get("bias_applied_count") or 0)
        tol = max(2, int(0.1 * max(bac, uplift_count, 1)))
        result["bias_l1_diff_uplift_aligned"] = abs(bac - uplift_count) <= tol

        # 6) Strategy rates (re-uses the already-defensive helper, does not
        # share a connection because it opens its own — safe, a bit wasteful
        # but keeps error isolation).
        result["strategy_rates"] = get_delegation_success_stats(
            task_type=task_type, query_fp=query_fp, project_root=project_root
        )
    except Exception:
        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return result
