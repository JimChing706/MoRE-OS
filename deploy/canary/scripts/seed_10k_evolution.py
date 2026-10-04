#!/usr/bin/env python3
"""Step 6 #2: Inject 10,000 deterministic evolution samples (seed 42).

Three buckets (baseline-proportional, user-approved Q2-A):
  local            =  7,800  (78%)  target pass_rate 38%
  chassis_default  =    800  ( 8%)  target pass_rate 82%
  chassis_evolution=  1,400  (14%)  target pass_rate 92%
                        TOTAL 10,000

Fault mix (35% density, user-approved Q3-A):
  20%  I-06 dirty-scratch -> PASS, bias tag applied (increases bac)
  10%  I-03 empty-output  -> FAIL
  5%   I-12 empty-output + tier-rollback -> PASS
  65%  normal             -> PASS/FAIL by bucket pass_rate dice

Before write: copies evolution DB -> .bak.$EPOCH (rollback: cp back).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MORE_SRC = REPO_ROOT / "more_core"
sys.path.insert(0, str(MORE_SRC))

from more_core.codegen.controller import adjudicate_codegen
from more_core.codegen.evolution_signal import (
    CodegenRunContext,
    _get_conn,
    _resolve_db_path,
    compute_evolution_summary,
    export_codegen_evolution_signal,
)

LOCAL_N = 7800
CHASSIS_DEF_N = 800
CHASSIS_EV_N = 1400
TOTAL_N = LOCAL_N + CHASSIS_DEF_N + CHASSIS_EV_N

LOCAL_PASS = 0.38
CHASSIS_DEF_PASS = 0.82
CHASSIS_EV_PASS = 0.92

I06_P = 0.20
I03_P = 0.10
I12_P = 0.05

TRIGGER_USER = "user_override"
TRIGGER_ESCALATION = "evolution_escalation"
TRIGGER_DEFAULT = "default_gate"
VERSION_TAG = "seed-10k"

BUCKET_LOCAL = "local"
BUCKET_CHASSIS_DEF = "chassis_default"
BUCKET_CHASSIS_EV = "chassis_evolution"


def _triggers_for_bucket(bucket: str, rng: random.Random) -> tuple[str, str]:
    """Return (delegation_trigger, delegation_state)."""
    if bucket == BUCKET_LOCAL:
        # Baseline local trigger distribution: "" 414/414 + default_gate rare.
        if rng.random() < 0.92:
            return "", ""
        return TRIGGER_DEFAULT, ""
    if bucket == BUCKET_CHASSIS_DEF:
        # ALL default_gate: strategy-bucket SQL strictly requires
        # delegation_trigger='default_gate' (user_override drops to UNASSIGNED).
        return TRIGGER_DEFAULT, "completed"
    # chassis_evolution: ALL via evolution_escalation (matches schema).
    return TRIGGER_ESCALATION, "completed"


def _make_sample(bucket: str, idx: int, rng: random.Random) -> tuple[dict, bool, dict]:
    """Return (scratch, sbx_success, run_ctx_extra)."""
    r = rng.random()
    pass_rate = {
        BUCKET_LOCAL: LOCAL_PASS,
        BUCKET_CHASSIS_DEF: CHASSIS_DEF_PASS,
        BUCKET_CHASSIS_EV: CHASSIS_EV_PASS,
    }[bucket]
    task_type = rng.choices(
        [
            "TaskType.CODE_GENERATION",
            "code_generation",
            "TaskType.CODE_DEBUGGING",
            "data_analysis",
            "code_review",
        ],
        weights=[339, 106, 44, 4, 1],
        k=1,
    )[0]
    extra: dict = {}
    if r < I06_P:
        # I-06: dirty scratch, heuristic PASS; writes bias tag via _bias_applied
        # so export picks it up into artifacts_json -> bac LIKE hit.
        scratch = {
            "code_fix_iterations": rng.randint(0, 1),
            "code_fix_deterministic": True,
            "code_review_summary": "[correctness:P1] heuristic fallback: confidence=0.0 "
            "I-06 dirty input; repaired via deterministic scan",
            "_bias_applied": f"delegation-bias applied (I-06 #{idx})",
            "rationale": f"delegation-bias applied (I-06 #{idx})",
            "l1_confidence": 0.0,
        }
        sbx_ok = True
    elif r < I06_P + I03_P:
        # I-03: empty output -> FAIL
        scratch = {
            "code_fix_iterations": rng.randint(1, 2),
            "code_fix_deterministic": False,
            "code_review_summary": "[correctness:P0] empty LLM output I-03; "
            "no fallback tier available; sandbox rejected",
        }
        sbx_ok = False
    elif r < I06_P + I03_P + I12_P:
        # I-12: empty output + tier-rollback PASS
        scratch = {
            "code_fix_iterations": rng.randint(2, 3),
            "code_fix_deterministic": True,
            "code_review_summary": "[correctness:P0] empty LLM output I-12; "
            "tier T1→T0 rollback passed P1-4",
            "tier_transition_record": f"T1→T0 (I-12 #{idx})",
        }
        sbx_ok = True
        extra["bias_l1_diff_uplift_applied"] = 1
    else:
        # Normal: PASS by bucket dice
        pass_dice = rng.random() < pass_rate
        scratch = {
            "code_fix_iterations": rng.randint(0, 2),
            "code_fix_deterministic": rng.random() < 0.55,
            "code_review_summary": "" if pass_dice else f"[correctness:P1] unit-test failure #{idx}",
        }
        if pass_dice and bucket != BUCKET_LOCAL and rng.random() < 0.18:
            scratch["_bias_applied"] = f"delegation-bias applied (chassis uplift #{idx})"
            scratch["rationale"] = f"delegation-bias applied (chassis uplift #{idx})"
        sbx_ok = pass_dice
    extra["task_type"] = task_type
    return scratch, sbx_ok, extra


def _iter_samples(rng: random.Random):
    for i in range(LOCAL_N):
        scratch, sbx_ok, extra = _make_sample(BUCKET_LOCAL, i, rng)
        trigger, dstate = _triggers_for_bucket(BUCKET_LOCAL, rng)
        yield BUCKET_LOCAL, scratch, sbx_ok, extra, trigger, dstate
    for i in range(CHASSIS_DEF_N):
        scratch, sbx_ok, extra = _make_sample(BUCKET_CHASSIS_DEF, LOCAL_N + i, rng)
        trigger, dstate = _triggers_for_bucket(BUCKET_CHASSIS_DEF, rng)
        yield BUCKET_CHASSIS_DEF, scratch, sbx_ok, extra, trigger, dstate
    for i in range(CHASSIS_EV_N):
        scratch, sbx_ok, extra = _make_sample(BUCKET_CHASSIS_EV, LOCAL_N + CHASSIS_DEF_N + i, rng)
        trigger, dstate = _triggers_for_bucket(BUCKET_CHASSIS_EV, rng)
        yield BUCKET_CHASSIS_EV, scratch, sbx_ok, extra, trigger, dstate


def _stats_dry_run(rng: random.Random) -> dict:
    stats = {
        BUCKET_LOCAL: {"n": 0, "p": 0},
        BUCKET_CHASSIS_DEF: {"n": 0, "p": 0},
        BUCKET_CHASSIS_EV: {"n": 0, "p": 0},
        "i06_count": 0,
        "i03_count": 0,
        "i12_count": 0,
        "bias_count": 0,
    }
    for bucket, scratch, sbx_ok, _extra, _trig, _dstate in _iter_samples(rng):
        stats[bucket]["n"] += 1
        if sbx_ok:
            stats[bucket]["p"] += 1
        bias_notes = ""
        for k in ("_bias_applied", "rationale", "advice"):
            v = scratch.get(k, "")
            if isinstance(v, str) and "delegation-bias applied" in v:
                bias_notes = v
                break
        if bias_notes:
            stats["bias_count"] += 1
        s = scratch.get("code_review_summary", "") or ""
        if "I-06" in s:
            stats["i06_count"] += 1
        elif "I-03" in s:
            stats["i03_count"] += 1
        elif "I-12" in s:
            stats["i12_count"] += 1
    return stats


def _backup_db(db_path: Path) -> Path:
    ts = int(time.time())
    bak = Path(str(db_path) + f".bak.seed10k-{ts}")
    shutil.copy2(db_path, bak)
    return bak


def _write_samples(db_path: Path, rng: random.Random) -> int:
    conn = _get_conn(db_path)
    created_at_base = time.time() - (TOTAL_N * 0.0001)
    written = 0
    try:
        with conn:
            for idx, (bucket, scratch, sbx_ok, extra, trigger, dstate) in enumerate(_iter_samples(rng)):
                verdict = adjudicate_codegen(scratch, scope="code", sbx_success=sbx_ok)
                ctx_extra = dict(extra)
                ctx_extra.setdefault("version", VERSION_TAG)
                ctx_extra.setdefault("seed_bucket", bucket)
                ctx_extra.setdefault("fault_tagged", bool(
                    scratch.get("code_review_summary", "").find("I-") >= 0
                ))
                # Inject delegation fields using the EXACT keys
                # export_codegen_evolution_signal actually reads.
                scratch_export = dict(scratch)
                if bucket != BUCKET_LOCAL:
                    scratch_export["_chassis_delegated"] = 1
                    scratch_export["_chassis_delegation_trigger"] = trigger
                    scratch_export["_chassis_delegation_state"] = dstate
                    scratch_export["code_delegated"] = 1
                    scratch_export["code_delegation_trigger"] = trigger
                    scratch_export["code_delegation_state"] = dstate
                    scratch_export["delegated"] = 1
                    scratch_export["delegation_trigger"] = trigger
                    scratch_export["delegation_state"] = dstate
                    if extra.get("bias_l1_diff_uplift_applied"):
                        scratch_export["diff_uplift_applied"] = 1
                        scratch_export["_bias_applied"] = "bias-l1-diff-uplift applied (I-12 tier rollback)"
                        scratch_export["rationale"] = "bias-l1-diff-uplift applied (I-12 tier rollback)"
                    scratch_export["tier_used"] = 1 if "T1" in scratch_export.get(
                        "tier_transition_record", "") else 0
                else:
                    scratch_export["_chassis_delegated"] = 0
                    scratch_export["code_delegated"] = 0
                    scratch_export["delegated"] = 0
                    scratch_export["_chassis_delegation_trigger"] = trigger
                    scratch_export["code_delegation_trigger"] = trigger
                    scratch_export["delegation_trigger"] = trigger
                    scratch_export["_chassis_delegation_state"] = dstate
                    scratch_export["code_delegation_state"] = dstate
                    scratch_export["delegation_state"] = dstate
                ctx = CodegenRunContext(
                    task_id=f"seed10k-{idx:05d}",
                    task_type=extra.get("task_type", "code_generation"),
                    query_fingerprint=f"seed10k-{idx % 9973:012d}",
                    scope="code",
                    project_root=str(MORE_SRC),
                    extra={"version": VERSION_TAG, **ctx_extra},
                )
                export_codegen_evolution_signal(
                    verdict,
                    scratch_export,
                    run_ctx=ctx,
                )
                written += 1
                if idx % 2000 == 1999:
                    print(f"  progress: written {written}/{TOTAL_N}", file=sys.stderr)
    finally:
        conn.close()
    return written


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 6 #2 seed 10k evolution samples")
    ap.add_argument("--seed", type=int, default=42, help="Random seed (default=42)")
    ap.add_argument("--db", type=str, default="", help="Override path to codegen_evolution.db")
    ap.add_argument("--dry-run", action="store_true", help="Only print predicted stats, no DB write")
    ap.add_argument("-y", "--yes", action="store_true", help="Skip backup confirmation")
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)

    if args.db:
        os.environ["MORE_CODEGEN_EVOLUTION_DB"] = args.db
    db_path = _resolve_db_path(str(MORE_SRC))
    print(f"[seed-10k] Target DB : {db_path}")
    print(f"[seed-10k] Seed      : {args.seed}")
    if args.dry_run:
        print("[seed-10k] DRY-RUN   : no write")

    pre = compute_evolution_summary()
    print(f"[seed-10k] Pre-state : total={pre['total_runs']} pass={pre['passed_runs']} "
          f"rate={_fmt_pct(pre['overall_pass_rate'])} bac={pre['bias_applied_count']}")

    if args.dry_run:
        stats = _stats_dry_run(rng)
        new_total = TOTAL_N
        new_pass = stats[BUCKET_LOCAL]["p"] + stats[BUCKET_CHASSIS_DEF]["p"] + stats[BUCKET_CHASSIS_EV]["p"]
        merged_total = pre["total_runs"] + new_total
        merged_pass = pre["passed_runs"] + new_pass
        merged_rate = (merged_pass / merged_total) if merged_total else 0.0
        print("--- dry-run predicted delta ---")
        print(json.dumps({
            "buckets": {
                k: {"n": v["n"], "passed": v["p"], "rate_pct": round(100 * (v["p"] / v["n"] if v["n"] else 0.0), 2)}
                for k, v in [(BUCKET_LOCAL, stats[BUCKET_LOCAL]),
                             (BUCKET_CHASSIS_DEF, stats[BUCKET_CHASSIS_DEF]),
                             (BUCKET_CHASSIS_EV, stats[BUCKET_CHASSIS_EV])]
            },
            "fault_counts": {"I06": stats["i06_count"], "I03": stats["i03_count"], "I12": stats["i12_count"]},
            "new_bias_count_delta": stats["bias_count"],
            "predicted_post": {
                "total_runs": merged_total,
                "passed_runs": merged_pass,
                "overall_pass_rate_pct": round(100 * merged_rate, 2),
                "bias_applied_count": pre["bias_applied_count"] + stats["bias_count"],
            },
            "TARGET_pass_rate_ge_45_pct": "PASS" if merged_rate >= 0.45 else "FAIL",
            "TARGET_bias_ge_110": "PASS" if (pre["bias_applied_count"] + stats["bias_count"]) >= 110 else "FAIL",
        }, ensure_ascii=False, indent=2))
        return 0

    # Real write: backup first
    if db_path.exists():
        if not args.yes:
            ans = input(f"About to write {TOTAL_N} rows. Create backup of {db_path} first? [Y/n] ").strip() or "y"
            if ans.lower() not in ("y", "yes"):
                print("Aborted.", file=sys.stderr)
                return 2
        bak = _backup_db(db_path)
        print(f"[seed-10k] Backup    : {bak}")
    else:
        bak = None
        print("[seed-10k] Backup    : skipped (DB did not exist yet)")

    t0 = time.time()
    written = _write_samples(db_path, rng)
    dt = time.time() - t0
    print(f"[seed-10k] Wrote {written}/{TOTAL_N} rows in {dt:.2f}s")

    post = compute_evolution_summary()
    local_post = post["strategy_rates"][BUCKET_LOCAL]
    cd_post = post["strategy_rates"][BUCKET_CHASSIS_DEF]
    ce_post = post["strategy_rates"][BUCKET_CHASSIS_EV]
    delta_n = post["total_runs"] - pre["total_runs"]
    delta_cd_n = int(cd_post["n"]) - int(pre["strategy_rates"][BUCKET_CHASSIS_DEF]["n"])
    delta_ce_n = int(ce_post["n"]) - int(pre["strategy_rates"][BUCKET_CHASSIS_EV]["n"])
    delta_local_n = int(local_post["n"]) - int(pre["strategy_rates"][BUCKET_LOCAL]["n"])
    rate_ok = post["overall_pass_rate"] >= 0.45
    bac_ok = post["bias_applied_count"] >= 110
    cd_delta = cd_post["rate"] - local_post["rate"]
    ce_delta = ce_post["rate"] - local_post["rate"]
    delta_ok = (cd_delta >= 0.05) and (ce_delta >= 0.05)
    print("--- post-write S state ---")
    print(json.dumps({
        "backup_path": str(bak) if bak else None,
        "delta_rows": {"total": delta_n, "local": delta_local_n,
                       "chassis_default": delta_cd_n, "chassis_evolution": delta_ce_n},
        "post": {
            "total_runs": post["total_runs"],
            "passed_runs": post["passed_runs"],
            "overall_pass_rate_pct": round(100 * post["overall_pass_rate"], 2),
            "bias_applied_count": post["bias_applied_count"],
            "strategy_rates": {
                k: {"n": int(v["n"]), "passed": int(v["passed"]),
                    "rate_pct": round(100 * v["rate"], 2)}
                for k, v in post["strategy_rates"].items()
            },
        },
        "S1_deltaN_eq_10000": "PASS" if delta_n == TOTAL_N else "FAIL",
        "S2_bucketDeltas_ok": "PASS" if (delta_local_n == LOCAL_N and
                                         delta_cd_n == CHASSIS_DEF_N and
                                         delta_ce_n == CHASSIS_EV_N) else "FAIL",
        "S3_overall_rate_ge_45": "PASS" if rate_ok else "FAIL",
        "S4_bac_ge_110": "PASS" if bac_ok else "FAIL",
        "S5_deltas_ge_5pp": {
            "chassis_default_local_gap_pp": round(100 * cd_delta, 2),
            "chassis_evolution_local_gap_pp": round(100 * ce_delta, 2),
            "PASS": bool(delta_ok),
        },
        "S6_backup_exists": "PASS" if (bak is None or Path(bak).exists()) else "FAIL",
    }, ensure_ascii=False, indent=2))
    return 0 if (written == TOTAL_N and rate_ok and bac_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
