"""Tests for the codegen loop Controller (`codegen/controller.py`).

The Controller is the deterministic metacognition role of the codegen Agentic
Loop (BPR §4/§13): it aggregates gate signals into an exit verdict and
escalates to P0 manual takeover when the success criteria are not met, while
preserving intermediate artifacts for the human.
"""

from __future__ import annotations

from more_core.codegen.controller import (
    DECISION_ESCALATED,
    DECISION_PARTIAL,
    DECISION_PASS,
    adjudicate_codegen,
)


class TestAdjudicatePass:
    def test_clean_pass(self):
        verdict = adjudicate_codegen({}, scope="code", sbx_success=True)
        assert verdict.ok
        assert verdict.decision == DECISION_PASS
        assert verdict.summary == "codegen loop passed all success criteria"
        assert verdict.checks["sandbox"] is True
        assert verdict.checks["assertions"] is False

    def test_pass_with_review_approved_no_p3(self):
        scratch = {"code_review_approved": True, "code_review": True}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_PASS
        assert verdict.checks["review"] == "approved"


class TestAdjudicatePartial:
    def test_review_approved_with_p3_is_partial(self):
        scratch = {
            "code_review_approved": True,
            "code_review_p3": ["minor: unused import"],
        }
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_PARTIAL
        assert verdict.reasons and "P3" in verdict.reasons[0]
        assert "codegen loop partial" in verdict.summary
        assert not verdict.ok

    def test_clean_pass_not_partial_when_review_off(self):
        verdict = adjudicate_codegen({}, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_PASS


class TestAdjudicateEscalated:
    def test_safety_block_escalates(self):
        scratch = {"code_fix_blocked": ["os.system in generated code"]}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_ESCALATED
        assert "safety check blocked" in verdict.reasons[0]

    def test_sandbox_failure_escalates(self):
        scratch = {"code_fix_iterations": 3}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=False, max_rounds=3)
        assert verdict.decision == DECISION_ESCALATED
        assert "sandbox failed after 3/3 fix rounds" in verdict.reasons[0]

    def test_assertions_required_not_verified_escalates(self):
        scratch = {"code_assertions_required": True, "code_fix_iterations": 1}
        verdict = adjudicate_codegen(
            scratch, scope="code", sbx_success=True, assertions_required=True
        )
        assert verdict.decision == DECISION_ESCALATED
        assert "acceptance assertions not verified" in verdict.reasons[0]

    def test_review_rejected_escalates(self):
        scratch = {"code_review_rejected": True, "code_review": True}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_ESCALATED
        assert "code review rejected" in verdict.reasons[0]

    def test_differential_disagreement_adds_reason(self):
        scratch = {"code_differential": True, "code_review_rejected": True}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_ESCALATED
        assert any("differential" in r for r in verdict.reasons)

    def test_stagnant_convergence_adds_reason(self):
        scratch = {"code_fix_stagnant": True, "code_fix_iterations": 3}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=False)
        assert verdict.decision == DECISION_ESCALATED
        assert any("stagnation" in r for r in verdict.reasons)


class TestArtifacts:
    def test_artifacts_preserved_for_p0_takeover(self):
        scratch = {
            "code_fix_iterations": 3,
            "code_best_of_k": True,
            "code_review_rejected": True,
            "code_review_summary": "2 P1 findings",
        }
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        artifacts = verdict.artifacts
        assert artifacts["fix_iterations"] == 3
        assert artifacts["best_of_k"] is True
        assert artifacts["review_summary"] == "2 P1 findings"
        assert artifacts["scope"] == "code"
        assert verdict.to_dict()["decision"] == DECISION_ESCALATED

    def test_to_dict_round_trip_keys(self):
        verdict = adjudicate_codegen({}, scope="code", sbx_success=True)
        data = verdict.to_dict()
        assert set(data) == {"decision", "checks", "reasons", "artifacts"}


class TestScopeIsolation:
    def test_other_scope_review_does_not_contaminate(self):
        scratch = {
            "test_review_rejected": True,
            "test_review_p3": ["minor"],
            "code_review_approved": True,
        }
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_PASS

    def test_short_form_blocked_flag_recognised(self):
        scratch = {"code_blocked": ["blocked"]}
        verdict = adjudicate_codegen(scratch, scope="code", sbx_success=True)
        assert verdict.decision == DECISION_ESCALATED
