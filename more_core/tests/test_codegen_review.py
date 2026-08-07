"""Tests for the multi-agent code review panel (`codegen/review.py`)."""

from __future__ import annotations

from more_core.codegen.review import (
    CodeReviewResult,
    ReviewerFinding,
    build_review_prompt,
    parse_review,
    run_code_review,
)


# =========================================================================
# Unit tests — parse_review
# =========================================================================


class TestParseReview:
    def test_bare_json(self):
        raw = '{"verdict": "approve", "severity": "P3", "findings": [], "suggestion": "ok"}'
        parsed = parse_review(raw, "correctness")
        assert parsed["verdict"] == "approve"
        assert parsed["severity"] == "P3"
        assert parsed["role"] == "correctness"

    def test_fenced_json_extracted(self):
        raw = 'text before\n```json\n{"verdict": "reject", "severity": "P1", "findings": ["x"]}\n```\ntext after'
        parsed = parse_review(raw, "security")
        assert parsed["verdict"] == "reject"
        assert parsed["severity"] == "P1"
        assert parsed["findings"] == ["x"]

    def test_missing_fields_get_defaults(self):
        parsed = parse_review('{"verdict": "reject"}', "quality")
        assert parsed["severity"] == "P2"
        assert parsed["findings"] == []
        assert parsed["suggestion"] == ""

    def test_invalid_verdict_normalised_to_reject(self):
        parsed = parse_review('{"verdict": "maybe", "severity": "P1"}', "quality")
        assert parsed["verdict"] == "reject"

    def test_invalid_severity_normalised_to_p2(self):
        parsed = parse_review('{"verdict": "reject", "severity": "P9"}', "quality")
        assert parsed["severity"] == "P2"

    def test_unparseable_degrades_to_reject_placeholder(self):
        parsed = parse_review("I think this code is fine overall", "correctness")
        assert parsed["verdict"] == "reject"
        assert parsed["severity"] == "P2"
        assert parsed["findings"] == ["评审者输出无法解析"]

    def test_empty_input_degrades(self):
        parsed = parse_review("", "correctness")
        assert parsed["verdict"] == "reject"


# =========================================================================
# Unit tests — build_review_prompt
# =========================================================================


class TestBuildReviewPrompt:
    def test_includes_role_task_code_and_schema(self):
        prompt = build_review_prompt(
            "sum two numbers", "def add(a, b): ...", "correctness", "你是正确性评审者"
        )
        assert "=== 评审者: correctness ===" in prompt
        assert "sum two numbers" in prompt
        assert "def add(a, b): ..." in prompt
        assert '"verdict": "approve" 或 "reject"' in prompt

    def test_query_truncated(self):
        long_query = "x" * 5000
        prompt = build_review_prompt(long_query, "code", "quality", "instruction")
        assert "x" * 4000 in prompt
        assert "x" * 5000 not in prompt


# =========================================================================
# Unit tests — CodeReviewResult
# =========================================================================


class TestCodeReviewResult:
    def test_summary_when_approved(self):
        result = CodeReviewResult(approved=True)
        assert result.summary == "code review approved (no P1/P2 findings)"

    def test_summary_lists_p1_p2_only(self):
        result = CodeReviewResult(
            approved=False,
            findings=[
                ReviewerFinding(role="security", severity="P1", message="eval on input"),
                ReviewerFinding(role="quality", severity="P3", message="rename var"),
            ],
        )
        assert "[security:P1] eval on input" in result.summary
        assert "rename var" not in result.summary

    def test_as_error_feeds_fix_loop(self):
        result = CodeReviewResult(
            approved=False,
            findings=[ReviewerFinding(role="correctness", severity="P2", message="off-by-one")],
        )
        error = result.as_error()
        assert error.startswith("code review rejected:")
        assert "off-by-one" in error


# =========================================================================
# Unit tests — run_code_review aggregation
# =========================================================================


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompt_tokens = 5
        self.completion_tokens = 7


class _FailingComplete:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, prompt: str) -> _FakeResp:
        self.calls += 1
        raise RuntimeError("LLM down")


class _PanelComplete:
    """Emulates the panel: correctness+quality approve, security rejects."""

    async def __call__(self, prompt: str) -> _FakeResp:
        if "=== 评审者: security ===" in prompt:
            return _FakeResp(
                '{"verdict": "reject", "severity": "P1", '
                '"findings": ["code uses eval on untrusted input"], "suggestion": "avoid eval"}'
            )
        return _FakeResp(
            '{"verdict": "approve", "severity": "P3", "findings": [], "suggestion": "fine"}'
        )


class TestRunCodeReview:
    async def test_panel_rejection_flags_p1_p2(self):
        result, in_tok, out_tok = await run_code_review(
            _PanelComplete(), "sum two numbers", "def add(a, b): pass"
        )
        assert not result.approved
        assert len(result.verdicts) == 3
        assert any(f.severity == "P1" and f.role == "security" for f in result.findings)
        assert in_tok == 15
        assert out_tok == 21

    async def test_all_approve(self):
        async def complete(prompt: str) -> _FakeResp:
            return _FakeResp('{"verdict": "approve", "severity": "P3", "findings": []}')

        result, _, _ = await run_code_review(complete, "sum two numbers", "def add(a, b): pass")
        assert result.approved
        assert result.findings == []

    async def test_all_reviewers_failing_fails_closed(self):
        result, _, _ = await run_code_review(
            _FailingComplete(), "sum two numbers", "def add(a, b): pass"
        )
        assert not result.approved
        assert result.errors
        assert len(result.errors) == 3
        assert "评审失败" in result.errors[0]

    async def test_partial_reviewer_failure_still_aggregates(self):
        class _PartialComplete:
            async def __call__(self, prompt: str) -> _FakeResp:
                if "=== 评审者: security ===" in prompt:
                    raise RuntimeError("LLM down")
                return _FakeResp('{"verdict": "approve", "severity": "P3", "findings": []}')

        result, _, _ = await run_code_review(_PartialComplete(), "sum", "code")
        assert len(result.errors) == 1
        assert len(result.verdicts) == 2
        assert result.approved

    async def test_whitespace_findings_are_skipped(self):
        async def complete(prompt: str) -> _FakeResp:
            return _FakeResp(
                '{"verdict": "reject", "severity": "P2", "findings": ["", "  ", "real bug"]}'
            )

        result, _, _ = await run_code_review(complete, "sum two numbers", "def add(a, b): pass")
        assert len(result.findings) == 3  # one per role
        assert all(f.message == "real bug" for f in result.findings)

    async def test_custom_roles(self):
        async def complete(prompt: str) -> _FakeResp:
            return _FakeResp('{"verdict": "approve", "severity": "P3", "findings": []}')

        result, _, _ = await run_code_review(
            complete, "sum two numbers", "def add(a, b): pass", roles=["quality"]
        )
        assert len(result.verdicts) == 1
        assert result.approved
