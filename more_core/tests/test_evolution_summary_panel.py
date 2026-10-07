"""EV-PANEL tests — evolution summary dashboard (10 tests).

Tests compute_evolution_summary() + /api/v1/evolution/summary HTTP endpoint.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from more_core.codegen.evolution_signal import (
    _get_conn,
    _resolve_db_path,
    compute_evolution_summary,
)

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app
from more_core.core.config import Settings
from more_core.runtime.orchestrator import MoRECore

TT = "code_generation"
QF = "src/utils.py"


def _seed_db(tmp_path, runs):
    project_root = Path(tmp_path) / "pr"
    project_root.mkdir()
    db_path = _resolve_db_path(str(project_root))
    conn = _get_conn(db_path)
    for i, r in enumerate(runs):
        artifacts = r.get("artifacts", {})
        conn.execute(
            "INSERT INTO codegen_runs(run_id,task_id,task_type,scope,query_fp,decision,"
            "fix_iterations,sandbox_ok,review_p3,differential,stagnant,blocked,best_of_k,"
            "assertions_ok,delegated,delegation_trigger,delegation_state,reasons_json,"
            "checks_json,artifacts_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"r{i}",
                f"t{i}",
                r.get("task_type", TT),
                "code",
                r.get("query_fp", QF),
                r["decision"],
                0,
                0,
                0,
                0,
                0,
                0,
                1,
                0,
                1 if r.get("delegated") else 0,
                r.get("trigger", ""),
                r.get("state", ""),
                "[]",
                "{}",
                json.dumps(artifacts),
                time.time() + i * 0.001,
            ),
        )
    conn.commit()
    conn.close()
    return project_root


def _mixed_runs():
    runs = []
    # local (trigger="" / delegated=0) ：50 runs 30 pass = 60%
    for i in range(50):
        runs.append(
            {
                "decision": "pass" if i < 30 else "partial",
                "delegated": False,
                "task_type": TT,
            }
        )
    # chassis_default 30 runs, 22 pass (73%)
    for i in range(30):
        runs.append(
            {
                "decision": "pass" if i < 22 else "partial",
                "delegated": True,
                "trigger": "default_gate",
                "state": "completed" if i < 22 else "failed",
                "task_type": TT,
            }
        )
    # chassis_evolution 40 runs, 36 pass (90%)
    for i in range(40):
        runs.append(
            {
                "decision": "pass" if i < 36 else "partial",
                "delegated": True,
                "trigger": "evolution_escalation",
                "state": "completed" if i < 36 else "failed",
                "task_type": TT,
                "artifacts": (
                    {"_bias_applied": True, "note": "delegation-bias applied: Δthreshold=+10%"}
                    if i % 5 == 0
                    else {}
                ),  # 40/5 = 8 bias_applied
            }
        )
    # 10 runs escalated
    for i in range(10):
        runs.append(
            {
                "decision": "escalated",
                "delegated": False,
                "task_type": "nlp_reasoning",
                "query_fp": "prompt1.txt",
            }
        )
    # 5 user_override
    for i in range(5):
        runs.append(
            {
                "decision": "pass",
                "delegated": True,
                "trigger": "user_override",
                "state": "completed",
                "task_type": TT,
            }
        )
    return runs


# ---------------------------------------------------------------------------
# 10 tests
# ---------------------------------------------------------------------------


class TestSummaryUnit:
    def test_01_empty_db_zeroed_shape(self, tmp_path):
        pr = Path(tmp_path) / "no_exist_pr_never_mkdir"
        s = compute_evolution_summary(project_root=str(pr))
        # 全部 key 存在且数值为 0/空
        assert s["total_runs"] == 0 and s["passed_runs"] == 0 and s["overall_pass_rate"] == 0.0
        for k in ("pass", "partial", "escalated"):
            assert s["decision_hist"][k] == 0
        for k in ("", "evolution_escalation", "default_gate", "user_override"):
            assert s["trigger_hist"].get(k, 0) == 0
        for k in ("local", "chassis_default", "chassis_evolution"):
            assert s["strategy_rates"][k]["n"] == 0
        assert s["bias_applied_count"] == 0
        assert s["top_task_types"] == []
        assert s["range"]["min_created_at"] is None and s["range"]["max_created_at"] is None

    def test_02_small_db_n_gt_0_rate_missing_sample(self, tmp_path):
        runs = []
        for _ in range(8):
            runs.append({"decision": "pass", "delegated": False})
        pr = _seed_db(tmp_path, runs)
        s = compute_evolution_summary(project_root=str(pr))
        assert s["total_runs"] == 8 and s["passed_runs"] == 8
        assert s["overall_pass_rate"] == pytest.approx(1.0)
        # strategy_rates local rate 为 0（样本数 n=8 <30）
        assert s["strategy_rates"]["local"]["n"] == 8
        assert s["strategy_rates"]["local"]["rate"] == 0.0
        # range 不为 None
        assert s["range"]["min_created_at"] is not None
        assert s["range"]["max_created_at"] >= s["range"]["min_created_at"]

    def test_03_mixed_trigger_histogram(self, tmp_path):
        pr = _seed_db(tmp_path, _mixed_runs())
        s = compute_evolution_summary(project_root=str(pr))
        assert s["trigger_hist"][""] == 50 + 10  # local 50 + escalated 10
        assert s["trigger_hist"]["default_gate"] == 30
        assert s["trigger_hist"]["evolution_escalation"] == 40
        assert s["trigger_hist"]["user_override"] == 5
        # decisions
        # passes: 30 local + 22 default + 36 evol + 5 user = 93 pass
        # partials: 20 local + 8 default + 4 evol = 32 partial
        # escalated: 10
        assert s["decision_hist"]["pass"] == 93
        assert s["decision_hist"]["partial"] == 32
        assert s["decision_hist"]["escalated"] == 10
        # total
        assert s["total_runs"] == 50 + 30 + 40 + 10 + 5

    def test_04_strategy_rates_after_mixed(self, tmp_path):
        pr = _seed_db(tmp_path, _mixed_runs())
        s = compute_evolution_summary(project_root=str(pr))
        # local: (50 code_gen local + 10 escalated (delegated=0)) = 60 runs;
        #        30 local code_generation passes + 0 nlp_reasoning passes = 30 / 60 = 50%
        assert s["strategy_rates"]["local"]["n"] == 60
        assert s["strategy_rates"]["local"]["rate"] == pytest.approx(0.50, abs=0.01)
        # chassis_default: 22/30 = 73.3%
        assert s["strategy_rates"]["chassis_default"]["n"] == 30
        assert s["strategy_rates"]["chassis_default"]["rate"] == pytest.approx(0.733, abs=0.02)
        # chassis_evolution: 36/40 = 90%
        assert s["strategy_rates"]["chassis_evolution"]["rate"] == pytest.approx(0.90, abs=0.01)

    def test_05_bias_applied_count(self, tmp_path):
        pr = _seed_db(tmp_path, _mixed_runs())
        s = compute_evolution_summary(project_root=str(pr))
        # In the 40 evolution runs, each 5th has "delegation-bias applied" in note → 8
        assert s["bias_applied_count"] == 8

    def test_06_top_task_types(self, tmp_path):
        pr = _seed_db(tmp_path, _mixed_runs())
        s = compute_evolution_summary(project_root=str(pr))
        # code_generation appears for (50+30+40+5) = 125 times; nlp_reasoning = 10 times
        top_types = dict(s["top_task_types"])
        assert top_types.get("code_generation", 0) == 125
        assert top_types.get("nlp_reasoning", 0) == 10
        # code_generation rank #1
        assert s["top_task_types"][0][0] == "code_generation"

    def test_07_filter_task_type_and_query_fp_works(self, tmp_path):
        pr = _seed_db(tmp_path, _mixed_runs())
        s_filtered = compute_evolution_summary(
            task_type="nlp_reasoning", query_fp="prompt1.txt", project_root=str(pr)
        )
        # 仅 10 条 nlp_reasoning/escalated
        assert s_filtered["total_runs"] == 10
        assert s_filtered["decision_hist"]["escalated"] == 10
        assert s_filtered["trigger_hist"][""] == 10
        # top task_types 仅 nlp_reasoning
        assert s_filtered["top_task_types"] == [("nlp_reasoning", 10)]

    def test_08_summary_never_raises_on_bad_path(self, tmp_path):
        # 指向不可写目录 + 不存在 pr 位置，应仍返回零值结构
        bad = "/tmp/surely_never_exists_qnm_12345/prj_non"
        s = compute_evolution_summary(project_root=bad)
        # 保证所有 expected key
        for k in (
            "total_runs",
            "passed_runs",
            "overall_pass_rate",
            "decision_hist",
            "trigger_hist",
            "strategy_rates",
            "bias_applied_count",
            "top_task_types",
            "range",
        ):
            assert k in s
        # 全部零值（或 None）；不 raise
        assert isinstance(s["decision_hist"], dict)


class TestSummaryHTTPEndpoint:
    def _mk_client(self, tmp_path):
        settings = Settings(
            providers=[],
            fallback_chain=[],
            enable_evolution=True,
            enable_metacognition=False,
            project_root=str(tmp_path / "pr"),
        )
        core = MoRECore(settings)
        from tests.conftest import _FakeLLMProvider

        core.llm._providers["fake"] = _FakeLLMProvider()
        core.llm._fallback = ["fake"]
        return TestClient(create_app(core))

    def test_09_http_endpoint_returns_shape(self, tmp_path):
        _seed_db(tmp_path, _mixed_runs())
        with self._mk_client(tmp_path) as client:
            resp = client.get("/api/v1/evolution/summary")
            assert resp.status_code == 200
            s = resp.json()
            assert s["total_runs"] == 135
            assert s["decision_hist"]["pass"] == 93
            assert s["trigger_hist"]["evolution_escalation"] == 40
            assert s["strategy_rates"]["local"]["n"] == 60  # 50 local + 10 escalated (delegated=0)
            assert s["bias_applied_count"] == 8

    def test_10_http_filtered_endpoint_query_params(self, tmp_path):
        _seed_db(tmp_path, _mixed_runs())
        with self._mk_client(tmp_path) as client:
            resp = client.get(
                "/api/v1/evolution/summary",
                params={"task_type": "nlp_reasoning", "query_fp": "prompt1.txt"},
            )
            assert resp.status_code == 200
            s = resp.json()
            assert s["total_runs"] == 10
            assert s["top_task_types"][0] == ["nlp_reasoning", 10]
            assert s["bias_applied_count"] == 0
