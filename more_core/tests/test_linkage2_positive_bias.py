"""Linkage-2 (LC2) tests — delegation success statistics + positive bias.

Covers 4+4+2 = 10 tests:
  1-4 get_delegation_success_stats unit (empty, small n, large n, filter by task_type+query_fp)
  5-8 _delegation_bias_for_query unit (no samples, <5pp, threshold relax, clamp to 0.75)
  9-10 query_dynamic_k_with_delegation_bias real SQLite integration (k stays 0 but rationale, k becomes 2)
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from more_core.codegen.evolution_signal import (
    _delegation_bias_for_query,
    _get_conn,
    _resolve_db_path,
    get_delegation_success_stats,
    query_dynamic_k,
    query_dynamic_k_with_delegation_bias,
)


TT = "code_generation"
QF = "src/utils.py"


def _seed_db(tmp_path: Path, runs):
    project_root = Path(tmp_path) / "pr"
    project_root.mkdir()
    db_path = _resolve_db_path(str(project_root))
    conn = _get_conn(db_path)
    for i, r in enumerate(runs):
        conn.execute(
            "INSERT INTO codegen_runs(run_id,task_id,task_type,scope,query_fp,decision,"
            "fix_iterations,sandbox_ok,review_p3,differential,stagnant,blocked,best_of_k,"
            "assertions_ok,delegated,delegation_trigger,delegation_state,reasons_json,"
            "checks_json,artifacts_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"r{i}", f"t{i}", r.get("task_type", TT), "code",
                r.get("query_fp", QF), r["decision"], 0, 0, 0, 0, 0, 0, 1, 0,
                1 if r.get("delegated") else 0,
                r.get("trigger", ""), r.get("state", ""),
                "[]", "{}", "{}", time.time() + i * 0.001,
            ),
        )
    conn.commit()
    conn.close()
    return project_root


# ---------------------------------------------------------------------------
# 1. get_delegation_success_stats (4)
# ---------------------------------------------------------------------------


class TestStats:
    def test_01_empty_db_zeroed(self, tmp_path):
        pr = Path(tmp_path) / "p"
        pr.mkdir()
        stats = get_delegation_success_stats(project_root=str(pr))
        for k in ("local", "chassis_default", "chassis_evolution"):
            assert stats[k]["n"] == 0 and stats[k]["passed"] == 0 and stats[k]["rate"] == 0.0

    def test_02_small_samples_rate_zero(self, tmp_path):
        runs = []
        for _ in range(10):
            runs.append({"decision": "pass", "delegated": False})
        for _ in range(10):
            runs.append({"decision": "pass", "delegated": True, "trigger": "default_gate", "state": "completed"})
        for _ in range(10):
            runs.append({"decision": "pass", "delegated": True, "trigger": "evolution_escalation", "state": "completed"})
        pr = _seed_db(tmp_path, runs)
        s = get_delegation_success_stats(project_root=str(pr))
        assert s["local"]["n"] == 10 and s["local"]["rate"] == 0.0
        assert s["chassis_default"]["n"] == 10 and s["chassis_default"]["rate"] == 0.0
        assert s["chassis_evolution"]["n"] == 10 and s["chassis_evolution"]["rate"] == 0.0

    def test_03_large_samples_rates_correct(self, tmp_path):
        runs = []
        for i in range(30): runs.append({"decision": "pass" if i < 15 else "partial", "delegated": False})  # 50%
        for i in range(30): runs.append({
            "decision": "pass" if i < 21 else "partial",
            "delegated": True, "trigger": "default_gate",
            "state": "completed" if i < 21 else "failed",
        })  # 70%
        for i in range(40): runs.append({
            "decision": "pass" if i < 36 else "partial",
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i < 36 else "failed",
        })  # 90%
        pr = _seed_db(tmp_path, runs)
        s = get_delegation_success_stats(project_root=str(pr))
        assert s["local"]["n"] == 30 and s["local"]["rate"] == pytest.approx(0.50, abs=0.01)
        assert s["chassis_default"]["n"] == 30 and s["chassis_default"]["rate"] == pytest.approx(0.70, abs=0.01)
        assert s["chassis_evolution"]["n"] == 40 and s["chassis_evolution"]["rate"] == pytest.approx(0.90, abs=0.01)

    def test_04_filter_task_and_fp(self, tmp_path):
        runs = []
        # Contamination group: different task_type — should NOT leak into filtered stats.
        for _ in range(50):
            runs.append({
                "decision": "partial", "delegated": True,
                "trigger": "evolution_escalation", "state": "failed",
                "task_type": "other_task",
            })
        # Target group.
        for i in range(40):
            runs.append({"decision": "pass" if i < 20 else "partial", "delegated": False})
        for i in range(40):
            runs.append({
                "decision": "pass" if i < 36 else "partial",
                "delegated": True, "trigger": "evolution_escalation",
                "state": "completed" if i < 36 else "failed",
            })
        pr = _seed_db(tmp_path, runs)
        s_all = get_delegation_success_stats(project_root=str(pr))
        assert s_all["chassis_evolution"]["n"] == 50 + 40
        s_filtered = get_delegation_success_stats(
            task_type=TT, query_fp=QF, project_root=str(pr)
        )
        assert s_filtered["local"]["n"] == 40
        assert s_filtered["local"]["rate"] == pytest.approx(0.50)
        assert s_filtered["chassis_evolution"]["n"] == 40
        assert s_filtered["chassis_evolution"]["rate"] == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# 2. _delegation_bias_for_query (4)
# ---------------------------------------------------------------------------


class TestBiasDecision:
    def test_05_low_samples_none_no_suffix(self, tmp_path):
        runs = []
        for _ in range(10): runs.append({"decision": "pass", "delegated": False})
        for _ in range(10): runs.append({
            "decision": "pass", "delegated": True,
            "trigger": "evolution_escalation", "state": "completed",
        })
        pr = _seed_db(tmp_path, runs)
        adj, suffix = _delegation_bias_for_query(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        assert adj is None and suffix == ""

    def test_06_uplift_below_5pp_no_go_suffix(self, tmp_path):
        runs = []
        for i in range(30): runs.append({"decision": "pass" if i < 24 else "partial", "delegated": False})  # 80%
        for i in range(30): runs.append({
            "decision": "pass" if i < 25 else "partial",  # 83% (Δ=+3pp)
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i < 25 else "failed",
        })
        pr = _seed_db(tmp_path, runs)
        adj, suffix = _delegation_bias_for_query(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        assert adj is None
        assert "delegation-bias" in suffix
        assert "uplift" in suffix

    def test_07_uplift_ok_relaxes_10pp(self, tmp_path):
        runs = []
        for i in range(30): runs.append({"decision": "pass" if i < 18 else "partial", "delegated": False})  # 60%
        for i in range(35): runs.append({
            "decision": "pass" if i < 32 else "partial",  # 91%
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i < 32 else "failed",
        })
        pr = _seed_db(tmp_path, runs)
        adj, suffix = _delegation_bias_for_query(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        assert adj == pytest.approx(0.65)
        assert "threshold 55% → 65%" in suffix
        assert "evolution" in suffix.lower()

    def test_08_clamped_at_0_75(self, tmp_path):
        runs = []
        for i in range(35): runs.append({"decision": "pass" if i < 21 else "partial", "delegated": False})
        for i in range(35): runs.append({
            "decision": "pass" if i >= 2 else "partial",
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i >= 2 else "failed",
        })
        pr = _seed_db(tmp_path, runs)
        adj, _ = _delegation_bias_for_query(
            task_type=TT, query_fp=QF, escalate_threshold=0.70, project_root=str(pr)
        )
        assert adj == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 3. query_dynamic_k_with_delegation_bias integration (2)
# ---------------------------------------------------------------------------


class TestBiasIntegration:
    def test_09_k_0_with_bias_rationale_applied_label(self, tmp_path):
        runs = []
        for i in range(40): runs.append({"decision": "pass" if i < 25 else "partial", "delegated": False})  # 62.5%
        for i in range(40): runs.append({
            "decision": "pass" if i < 36 else "partial",
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i < 36 else "failed",
        })  # 90%
        pr = _seed_db(tmp_path, runs)
        k_base, r_base = query_dynamic_k(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        # Overall (25+36)/80 = 76.25% ≥ 55% → no escalation
        assert k_base == 0 and "single-gen baseline OK" in r_base
        # Positive bias triggers: 90% − 62.5% = +27.5% uplift.
        k_bias, r_bias = query_dynamic_k_with_delegation_bias(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        # Threshold relaxes to 65% — overall still ≥ 65%, so stays k=0, but applied label appears
        assert k_bias == 0
        assert "delegation-bias applied" in r_bias
        assert "Δthreshold=+10%" in r_bias

    def test_10_k_2_after_bias_relax(self, tmp_path):
        runs = []
        # 30 local: 50% pass, 30 evolution: 86.7% pass → Δ=+36.7% uplift → bias relax 0.55→0.65
        for i in range(30): runs.append({"decision": "pass" if i < 15 else "partial", "delegated": False})
        for i in range(30): runs.append({
            "decision": "pass" if i < 26 else "partial",
            "delegated": True, "trigger": "evolution_escalation",
            "state": "completed" if i < 26 else "failed",
        })
        # Add 10 local failed runs → total passes=41 / 70 = 58.6% < 0.65 → k=2
        for _ in range(10): runs.append({"decision": "partial", "delegated": False})
        pr = _seed_db(tmp_path, runs)
        k, r = query_dynamic_k_with_delegation_bias(
            task_type=TT, query_fp=QF, escalate_threshold=0.55, project_root=str(pr)
        )
        assert k == 2
        assert "delegation-bias applied" in r
        assert "escalating to best-of-2" in r
