"""Tests for the Codegen → L2 Evolution signal bridge (`codegen/evolution_signal.py`).

Verifies:
  * Export persists runs / failures / fix-patterns into SQLite
  * Adjudication with run_ctx != None attaches evolution_run_id to artifacts
  * Failure class fingerprinting normalises line numbers / paths / hex values
  * L2 query API (query_top_fixes_for_failure, query_verdict_stats) returns
    correctly-aggregated rows after a multi-run seed
  * Export never raises (defensive; DB unavailable falls through silently)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from more_core.codegen.controller import (
    DECISION_ESCALATED,
    DECISION_PARTIAL,
    DECISION_PASS,
    adjudicate_codegen,
)
from more_core.codegen.evolution_signal import (
    CodegenRunContext,
    _fingerprint,
    classify_failure,
    export_codegen_evolution_signal,
    query_top_fixes_for_failure,
    query_verdict_stats,
)


# ── Fingerprint / classification unit tests ──────────────────────────────────


class TestFingerprint:
    def test_fingerprint_normalises_line_numbers(self):
        a = "SyntaxError at line 123: invalid syntax"
        b = "SyntaxError at line 9999: invalid syntax"
        assert _fingerprint(a) == _fingerprint(b)

    def test_fingerprint_normalises_paths(self):
        a = 'File "/home/alice/project/foo.py" line 1'
        b = 'File "/tmp/bar/other/foo.py" line 2'
        assert _fingerprint(a) == _fingerprint(b)

    def test_fingerprint_normalises_hex(self):
        a = "got pointer 0xdeadbeef and 0xC0FFEE"
        b = "got pointer 0x11111111 and 0x22222222"
        assert _fingerprint(a) == _fingerprint(b)

    def test_empty_string_is_stable(self):
        assert _fingerprint("") == _fingerprint("")
        assert _fingerprint("") == "empty"


class TestClassifyFailure:
    def test_syntax_error_detected(self):
        cls, fp = classify_failure("SyntaxError: invalid syntax at line 10")
        assert cls == "syntax_error"
        assert fp

    def test_import_error_detected(self):
        cls, _ = classify_failure("ModuleNotFoundError: No module named 'foo'")
        assert cls == "import_error"

    def test_name_type_attribute_errors(self):
        assert classify_failure("NameError: name 'x' is not defined")[0] == "name_error"
        assert classify_failure("TypeError: expected int")[0] == "type_error"
        assert classify_failure("AttributeError: no attr")[0] == "attribute_error"

    def test_assertion_and_test_failures(self):
        assert classify_failure("AssertionError: 1 != 2")[0] == "assertion_failed"
        assert classify_failure("FAILED tests/foo.py::test_bar - blah")[0] == "test_failure"

    def test_lint_and_review(self):
        assert classify_failure("ruff: E501 line too long")[0] == "lint_error"
        assert classify_failure("P1 finding: SQL injection in route")[0] == "review_p1_p2"

    def test_safety_stagnation_differential(self):
        assert classify_failure("safety blocked: dangerous code")[0] == "safety_blocked"
        assert classify_failure("stagnant converged no progress")[0] == "stagnation"
        assert classify_failure("differential outputs disagreed")[0] == "differential"

    def test_unknown_falls_to_other(self):
        cls, _ = classify_failure("some totally new problem nobody tagged")
        assert cls == "other"


# ── Export integration (tmp DB) ─────────────────────────────────────────────


@pytest.fixture
def tmp_db(monkeypatch, tmp_path: Path):
    db_file = tmp_path / "cg.db"
    monkeypatch.setenv("MORE_CODEGEN_EVOLUTION_DB", str(db_file))
    yield db_file


class TestExportCodegenEvolutionSignal:
    def test_export_creates_tables_and_run_row(self, tmp_db: Path):
        verdict = adjudicate_codegen({}, scope="code", sbx_success=True)
        run_id = export_codegen_evolution_signal(
            verdict,
            {},
            run_ctx=CodegenRunContext(
                task_id="t-1",
                task_type="code_generation",
                scope="code",
                project_root=str(tmp_db.parent),
            ),
        )
        assert run_id is not None
        assert tmp_db.exists()
        with sqlite3.connect(tmp_db) as c:
            (decision, task_type, t_id) = c.execute(
                "SELECT decision, task_type, task_id FROM codegen_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        assert decision == DECISION_PASS
        assert task_type == "code_generation"
        assert t_id == "t-1"

    def test_escalated_with_review_rejected_writes_failure_rows(self, tmp_db: Path):
        scratch = {
            "code_review_rejected": True,
            "code_review_summary": "2 P1 findings: SQL injection, XSS",
            "code_fix_iterations": 2,
            "code_fix_stagnant": True,
        }
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        run_id = export_codegen_evolution_signal(
            verdict,
            scratch,
            run_ctx=CodegenRunContext(task_id="t-2", task_type="code_debugging"),
        )
        assert run_id
        with sqlite3.connect(tmp_db) as c:
            failures = c.execute(
                "SELECT failure_class, failure_text FROM codegen_failure_modes WHERE run_id=?",
                (run_id,),
            ).fetchall()
            classes = {r[0] for r in failures}
        assert verdict.decision == DECISION_ESCALATED
        assert "review_p1_p2" in classes
        assert "stagnation" in classes

    def test_sandbox_failure_attaches_error_body(self, tmp_db: Path):
        class FakeSbx:
            success = False
            error = "NameError: name 'foo' is not defined\n  at line 5\n"
            output = ""

        scratch = {"code_fix_iterations": 2, "sandbox_result": FakeSbx()}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=False, max_rounds=3)
        run_id = export_codegen_evolution_signal(
            verdict, scratch, run_ctx=CodegenRunContext(task_type="code_generation")
        )
        assert run_id
        with sqlite3.connect(tmp_db) as c:
            classes = [
                r[0]
                for r in c.execute(
                    "SELECT failure_class FROM codegen_failure_modes WHERE run_id=?",
                    (run_id,),
                ).fetchall()
            ]
        assert verdict.decision == DECISION_ESCALATED
        assert "name_error" in classes

    def test_adjudicate_with_run_ctx_attaches_run_id(self, tmp_db: Path):
        scratch = {"code_fix_iterations": 1}
        verdict = adjudicate_codegen(
            scratch,
            scope="code",
            sbx_success=True,
            run_ctx=CodegenRunContext(task_id="t-3"),
        )
        assert verdict.artifacts.get("evolution_run_id")

    def test_adjudicate_without_run_ctx_is_unaffected(self):
        """Backwards compat: callers not passing run_ctx see zero behaviour change."""
        verdict = adjudicate_codegen({}, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_PASS
        assert "evolution_run_id" not in verdict.artifacts

    def test_export_defensive_never_raises(self, tmp_db: Path):
        class BrokenVerdict:
            def to_dict(self):
                raise RuntimeError("boom")

        # Should not raise; returns None
        assert (
            export_codegen_evolution_signal(
                BrokenVerdict(),
                {},
                run_ctx=CodegenRunContext(),
            )
            is None
        )


# ── L2 query API aggregation ────────────────────────────────────────────────


class TestL2QueryAPI:
    def _seed(self, tmp_db: Path) -> None:
        """Seed 12 runs covering import_error / lint_error mixed outcomes."""
        for i in range(6):  # 6 import_error runs — first 3 determistic wins
            scratch = {
                "code_fix_iterations": 2,
                "code_fix_deterministic": True,
                "sandbox_result": type(
                    "SB",
                    (),
                    {
                        "success": i < 4,
                        "error": "ModuleNotFoundError: missing_foo"
                        if i < 5
                        else "",
                        "output": "",
                    },
                )(),
            }
            v = adjudicate_codegen(
                scratch, scope="code", sbx_success=(i < 4)
            )
            export_codegen_evolution_signal(
                v,
                scratch,
                run_ctx=CodegenRunContext(task_type="code_generation"),
            )
        for i in range(4):  # 4 lint_error runs — llm wins
            scratch = {
                "code_fix_iterations": 1,
                "code_review_approved": True if i < 3 else False,
                "code_review_p3": ["unused import"] if i < 3 else [],
                "code_review_summary": "ruff: E501 line too long" if i >= 3 else "",
                "sandbox_result": type(
                    "SB", (), {"success": True, "error": "", "output": ""}
                )(),
            }
            v = adjudicate_codegen(
                scratch, scope="code", sbx_success=True
            )
            export_codegen_evolution_signal(
                v,
                scratch,
                run_ctx=CodegenRunContext(task_type="code_debugging"),
            )
        # 2 unknown-class runs escalated
        for _i in range(2):
            scratch = {"code_fix_iterations": 3, "code_fix_stagnant": True}
            v = adjudicate_codegen(scratch, scope="code", sbx_success=False)
            export_codegen_evolution_signal(
                v, scratch, run_ctx=CodegenRunContext()
            )

    def test_query_verdict_stats_aggregates(self, tmp_db: Path):
        self._seed(tmp_db)
        stats = query_verdict_stats(last_n_days=None)
        assert stats["total_runs"] == 12
        assert stats["by_decision"].get(DECISION_PASS, 0) >= 1
        assert any(
            fc["failure_class"] == "import_error" for fc in stats["top_failure_classes"]
        )

    def test_query_top_fixes_min_samples_gate(self, tmp_db: Path):
        self._seed(tmp_db)
        # min_samples=100 → no rows
        rows = query_top_fixes_for_failure("import_error", min_samples=100)
        assert rows == []
        # min_samples=1 → rows present, deterministic > llm by design of seed
        rows = query_top_fixes_for_failure("import_error", min_samples=1)
        assert rows
        kinds = [r["fix_kind"] for r in rows]
        assert "deterministic" in kinds
        assert "llm" in kinds
        for r in rows:
            assert 0.0 <= r["success_rate"] <= 1.0
            assert r["samples"] >= r["successful_samples"]

    def test_partial_decision_is_counted(self, tmp_db: Path):
        scratch = {
            "code_review_approved": True,
            "code_review_p3": ["minor whitespace"],
        }
        v = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert v.decision == DECISION_PARTIAL
        export_codegen_evolution_signal(
            v, scratch, run_ctx=CodegenRunContext(task_type="code_review")
        )
        stats = query_verdict_stats(last_n_days=None)
        assert stats["by_decision"].get(DECISION_PARTIAL, 0) == 1


# ── Existing controller tests still pass when evolution module raises ───────


class TestControllerBackwardsCompat:
    def test_all_original_paths_without_runctx(self):
        """Sanity: 100% of the controller's decision matrix still works."""
        # clean pass
        v = adjudicate_codegen({}, scope="code", sbx_success=True)
        assert v.decision == DECISION_PASS
        # safety
        v = adjudicate_codegen(
            {"code_blocked": ["os.system used"]}, scope="code", sbx_success=True
        )
        assert v.decision == DECISION_ESCALATED and "safety" in v.reasons[0]
        # sandbox fail
        v = adjudicate_codegen(
            {"code_fix_iterations": 3}, scope="code", sbx_success=False, max_rounds=3
        )
        assert v.decision == DECISION_ESCALATED and "3/3" in v.reasons[0]
        # assertions required
        v = adjudicate_codegen(
            {}, scope="code", sbx_success=True, assertions_required=True
        )
        assert v.decision == DECISION_ESCALATED and "assertions" in v.reasons[0]
        # review rejected
        v = adjudicate_codegen(
            {"code_review_rejected": True}, scope="code", sbx_success=True
        )
        assert v.decision == DECISION_ESCALATED and "review rejected" in v.reasons[0]
        # partial (P3 only)
        v = adjudicate_codegen(
            {"code_review_approved": True, "code_review_p3": ["unused import"]},
            scope="code",
            sbx_success=True,
        )
        assert v.decision == DECISION_PARTIAL
