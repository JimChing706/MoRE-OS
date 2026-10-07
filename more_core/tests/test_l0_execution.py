"""Tests for L0 execution layer — LLM generation + tool dispatch loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskStatus, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l0_execution import (
    ExecutionLayer,
    _extract_llm_confidence,
)
from more_core.llm.provider import LLMResponse
from more_core.tools.registry import ToolResult

# =========================================================================
# Unit tests — _is_clarification_question
# =========================================================================


class TestIsClarificationQuestion:
    def setup_method(self) -> None:
        self._method = staticmethod(ExecutionLayer._is_clarification_question).__func__

    def test_short_text_returns_false(self):
        assert self._method("") is False
        assert self._method("Hi") is False
        assert self._method("A" * 14) is False

    def test_code_fence_returns_false(self):
        assert self._method("```python\nprint('hello')\n```") is False

    def test_dense_indented_lines_returns_false(self):
        text = "\n".join("    line" + str(i) for i in range(5))
        assert self._method(text) is False

    def test_long_output_returns_false(self):
        assert self._method("A" * 1500) is False

    def test_short_question_ending_with_question_mark(self):
        assert self._method("What framework should I use?") is True

    def test_chinese_question_indicator(self):
        assert self._method("我想问你希望我用哪种方式来实现这个") is True
        assert self._method("请告诉我你想要什么颜色方案比较好看") is True

    def test_japanese_question_indicator(self):
        assert self._method("どちらがいいですか教えてくださいませんか") is True

    def test_korean_question_indicator(self):
        assert self._method("어떻게 할까요 알려주시면 감사하겠습니다") is True

    def test_normal_code_output_not_a_question(self):
        assert self._method("def hello():\n    return 'world'") is False

    def test_question_pattern_in_english(self):
        assert self._method("Would you like me to use Flask or FastAPI?") is True
        assert self._method("Which approach do you prefer?") is True
        assert self._method("Let me know your requirements") is True

    def test_question_mark_within_long_text_not_question(self):
        assert self._method("Line 1\n\nLine 2?\n" + "A" * 500) is False


# =========================================================================
# Unit tests — _extract_python
# =========================================================================


class TestExtractPython:
    def setup_method(self) -> None:
        self._method = staticmethod(ExecutionLayer._extract_python).__func__

    def test_extract_python_fence(self):
        code = 'print("hello")'
        text = f"Some text\n```python\n{code}\n```\nmore text"
        assert self._method(text) == code

    def test_extract_py_fence(self):
        code = "x = 1"
        text = f"Text\n```py\n{code}\n```\nend"
        assert self._method(text) == code

    def test_no_fence_returns_empty(self):
        assert self._method("just plain text") == ""

    def test_empty_text_returns_empty(self):
        assert self._method("") == ""

    def test_multiple_code_blocks_returns_first(self):
        text = "```py\na=1\n```\n```py\nb=2\n```"
        assert self._method(text) == "a=1"

    def test_incomplete_fence_returns_empty(self):
        text = "```python\ncode without closing"
        assert self._method(text) == ""

    def test_fence_case_insensitive(self):
        code = 'print("hi")'
        text = f"```PYTHON\n{code}\n```"
        assert self._method(text) == code

    def test_structured_json_code(self):
        text = '{"code": "print(\\"hi\\")", "language": "python"}'
        assert self._method(text) == 'print("hi")'

    def test_structured_json_with_source_key(self):
        text = '{"source": "x = 1", "language": "py"}'
        assert self._method(text) == "x = 1"

    def test_bare_code_compiles_and_is_extracted(self):
        assert (
            self._method("def add(a, b):\n    return a + b") == "def add(a, b):\n    return a + b"
        )

    def test_bare_code_import_extracted(self):
        assert self._method("import math\nprint(math.pi)") == "import math\nprint(math.pi)"

    def test_prose_returns_empty(self):
        assert self._method("just plain text") == ""


# =========================================================================
# Unit tests — _extract_test_code
# =========================================================================


class TestExtractTestCode:
    def setup_method(self) -> None:
        self._method = staticmethod(ExecutionLayer._extract_test_code).__func__

    def test_extract_python_test_fence(self):
        code = "def test_hello(): pass"
        text = f"```python test\n{code}\n```"
        assert self._method(text) == code

    def test_extract_python_pytest_fence(self):
        code = "def test_foo(): assert 1"
        text = f"```python pytest\n{code}\n```"
        assert self._method(text) == code

    def test_extract_python_unittest_fence(self):
        code = "class TestFoo(unittest.TestCase): pass"
        text = f"```python unittest\n{code}\n```"
        assert self._method(text) == code

    def test_fallback_to_python_fence_with_test_keyword(self):
        code = "def test_something(): assert True"
        text = f"```python\n{code}\n```"
        assert self._method(text) == code

    def test_fallback_with_pytest_import(self):
        code = "import pytest\ndef test_x(): pass"
        text = f"```python\n{code}\n```"
        assert self._method(text) == code

    def test_no_test_code_returns_empty(self):
        text = "```python\nx = 1\n```"
        assert self._method(text) == ""

    def test_no_fence_returns_empty(self):
        assert self._method("just text") == ""


# =========================================================================
# Unit tests — _compute_confidence
# =========================================================================


class TestComputeConfidence:
    def _make_ctx(self, scratch: dict | None = None, steps: list | None = None) -> LayerContext:
        core = MagicMock()
        core.settings = MagicMock()
        core.settings.codegen_review = False
        core.settings.codegen_candidates = 1
        req = MagicMock()
        req.query = "test"
        req.type = TaskType.NLP_TASK
        ctx = LayerContext(core=core, request=req)
        if scratch:
            ctx.scratch.update(scratch)
        if steps:
            ctx.accumulated_steps = steps
        return ctx

    def test_sandbox_success_returns_high_confidence(self):
        from more_core.tools.registry import ToolResult

        sbx = ToolResult(tool="python_exec", success=True, output="ok")
        ctx = self._make_ctx({"sandbox_result": sbx})
        assert ExecutionLayer._compute_confidence(ctx) == 0.95

    def test_sandbox_failure_returns_low_confidence(self):
        from more_core.tools.registry import ToolResult

        sbx = ToolResult(tool="python_exec", success=False, output="fail", error="err")
        ctx = self._make_ctx({"sandbox_result": sbx})
        assert ExecutionLayer._compute_confidence(ctx) == 0.2

    def test_code_blocked_returns_very_low(self):
        ctx = self._make_ctx({"code_blocked": ["danger"]})
        assert ExecutionLayer._compute_confidence(ctx) == 0.15

    def test_llm_confidence_parsed(self):
        ctx = self._make_ctx({"_l0_raw_output": "ok\n<!-- confidence: 0.75 -->"})
        assert ExecutionLayer._compute_confidence(ctx) == 0.75

    def test_llm_confidence_averaged_with_previous_steps(self):
        from more_core.core.types import ReasoningStep

        steps = [
            ReasoningStep(id=1, layer=LayerId.L1, description="x", duration_ms=1.0, confidence=0.9),
            ReasoningStep(id=2, layer=LayerId.L3, description="y", duration_ms=1.0, confidence=0.7),
        ]
        ctx = self._make_ctx({"_l0_raw_output": "ok\n<!-- confidence: 0.85 -->"}, steps=steps)
        expected = round((0.85 + (0.9 + 0.7) / 2) / 2, 2)
        assert ExecutionLayer._compute_confidence(ctx) == expected

    def test_no_sandbox_no_llm_conf_falls_back_to_step_average(self):
        from more_core.core.types import ReasoningStep

        steps = [
            ReasoningStep(id=1, layer=LayerId.L1, description="x", duration_ms=1.0, confidence=0.8),
            ReasoningStep(id=2, layer=LayerId.L3, description="y", duration_ms=1.0, confidence=0.6),
        ]
        ctx = self._make_ctx({}, steps=steps)
        assert ExecutionLayer._compute_confidence(ctx) == 0.7

    def test_no_signals_returns_default(self):
        ctx = self._make_ctx()
        assert ExecutionLayer._compute_confidence(ctx) == 0.85

    def test_escalated_verdict_returns_very_low_confidence(self):
        ctx = self._make_ctx({"codegen_verdict": {"decision": "escalated"}})
        assert ExecutionLayer._compute_confidence(ctx) == 0.1

    def test_partial_verdict_returns_mid_confidence(self):
        ctx = self._make_ctx({"codegen_verdict": {"decision": "partial"}})
        assert ExecutionLayer._compute_confidence(ctx) == 0.5

    def test_pass_verdict_does_not_override_sandbox_confidence(self):
        from more_core.tools.registry import ToolResult

        sbx = ToolResult(tool="python_exec", success=True, output="ok")
        ctx = self._make_ctx({"codegen_verdict": {"decision": "pass"}, "sandbox_result": sbx})
        assert ExecutionLayer._compute_confidence(ctx) == 0.95


# =========================================================================
# Unit tests — _build_annotation_guidance
# =========================================================================


class TestBuildAnnotationGuidance:
    def setup_method(self) -> None:
        self._method = staticmethod(ExecutionLayer._build_annotation_guidance).__func__

    def test_code_review_with_dimensions(self):
        ann = {"review_dimensions": ["security", "performance"]}
        result = self._method(ann, TaskType.CODE_REVIEW)
        assert "security" in result
        assert "performance" in result
        assert "评分" in result

    def test_architecture_design_with_checklist(self):
        ann = {
            "architecture_checklist": [
                {"dim": "scalability", "items": ["水平扩展"]},
            ],
        }
        result = self._method(ann, TaskType.ARCHITECTURE_DESIGN)
        assert "scalability" in result
        assert "水平扩展" in result

    def test_with_artifacts_expected(self):
        ann = {"artifacts_expected": ["架构图", "API设计"]}
        result = self._method(ann, TaskType.NLP_TASK)
        assert "架构图" in result
        assert "API设计" in result

    def test_empty_annotations(self):
        assert self._method({}, TaskType.NLP_TASK) == ""


# =========================================================================
# Unit tests — _check_code_safety
# =========================================================================


class TestCheckCodeSafety:
    def _make_ctx(self, l3_available: bool = True, l3_has_rule_engine: bool = True) -> LayerContext:
        core = MagicMock()
        core.settings = MagicMock()
        core.settings.codegen_review = False
        core.settings.codegen_candidates = 1
        req = MagicMock()
        req.query = "test"
        req.type = TaskType.CODE_GENERATION
        ctx = LayerContext(core=core, request=req)

        if l3_available:
            if l3_has_rule_engine:
                from more_core.ontology.rule_engine import RuleEngine

                l3 = MagicMock()
                l3.rule_engine = RuleEngine()
                from more_core.ontology.rule_engine import default_governance_rules

                for r in default_governance_rules():
                    l3.rule_engine.add_rule(r)
            else:
                l3 = MagicMock(spec=[])  # no rule_engine attribute
            core.get_layer.return_value = l3
        else:
            core.get_layer.side_effect = KeyError("L3 not found")
        return ctx

    def test_safe_code_passes(self):
        ctx = self._make_ctx()
        safe, violations = ExecutionLayer._check_code_safety("print('hello')", ctx)
        assert safe is True
        assert violations == []

    def test_dangerous_os_system_detected(self):
        ctx = self._make_ctx()
        safe, violations = ExecutionLayer._check_code_safety("os.system('rm -rf /')", ctx)
        assert safe is False
        assert any("dangerous" in v for v in violations)

    def test_dangerous_eval_detected(self):
        ctx = self._make_ctx()
        safe, _violations = ExecutionLayer._check_code_safety("eval('x')", ctx)
        assert safe is False

    def test_dangerous_exec_detected(self):
        ctx = self._make_ctx()
        safe, _violations = ExecutionLayer._check_code_safety("exec('x')", ctx)
        assert safe is False

    def test_dangerous_subprocess_call_detected(self):
        ctx = self._make_ctx()
        safe, _violations = ExecutionLayer._check_code_safety("subprocess.call('ls')", ctx)
        assert safe is False

    def test_fallback_when_l3_unavailable(self):
        ctx = self._make_ctx(l3_available=False)
        safe, _violations = ExecutionLayer._check_code_safety("eval('danger')", ctx)
        assert safe is False

    def test_safe_code_when_l3_unavailable(self):
        ctx = self._make_ctx(l3_available=False)
        safe, _violations = ExecutionLayer._check_code_safety("print('ok')", ctx)
        assert safe is True

    def test_l3_without_rule_engine_falls_back(self):
        ctx = self._make_ctx(l3_available=True, l3_has_rule_engine=False)
        safe, _violations = ExecutionLayer._check_code_safety("print('ok')", ctx)
        assert safe is True


# =========================================================================
# Unit tests — _extract_llm_confidence
# =========================================================================


class TestExtractLLMConfidence:
    def test_extracts_confidence(self):
        assert _extract_llm_confidence("ok\n<!-- confidence: 0.85 -->") == 0.85

    def test_extracts_with_comma_separator(self):
        assert _extract_llm_confidence("ok\n<!-- confidence: 0,92 -->") == 0.92

    def test_no_match_returns_none(self):
        assert _extract_llm_confidence("no confidence tag") is None

    def test_empty_text_returns_none(self):
        assert _extract_llm_confidence("") is None

    def test_clamps_to_range(self):
        assert _extract_llm_confidence("<!-- confidence: 5.00 -->") == 1.0


# =========================================================================
# Unit tests — fix loop (_run_fix_loop)
# =========================================================================


class TestRunFixLoop:
    def _make_ctx(self, core=None, scratch: dict | None = None) -> LayerContext:
        if core is None:
            core = MagicMock()
            core.settings = MagicMock()
            core.settings.codegen_review = False
            core.settings.codegen_candidates = 1
        req = MagicMock()
        req.id = "fix-loop-test"
        req.type = TaskType.CODE_GENERATION
        req.context = {}
        ctx = LayerContext(core=core, request=req)
        if scratch:
            ctx.scratch.update(scratch)
        return ctx

    def _sbx(self, success: bool, error: str = "") -> ToolResult:
        return ToolResult(
            tool="python_exec",
            success=success,
            output="ok" if success else "",
            error=error,
            duration_ms=1.0,
        )

    def _llm_response(self, content: str) -> LLMResponse:
        return LLMResponse(
            content=content,
            provider="fake",
            model="fake-model",
            prompt_tokens=10,
            completion_tokens=20,
        )

    async def _run(
        self,
        ctx,
        invoke_results,
        *,
        gen_content,
        scope="code",
        code="print('x')",
        assertions=None,
    ):
        from more_core.llm.provider import LLMRequest

        ctx.core.tools.invoke = AsyncMock(side_effect=invoke_results)
        ctx.core.llm.generate = AsyncMock(return_value=self._llm_response(gen_content))
        ctx.core.get_layer.side_effect = KeyError("L3 not found")
        ctx.core.audit.log = MagicMock()
        gen_req = LLMRequest(prompt="write code", system="sys", temperature=0.7, max_tokens=100)
        layer = ExecutionLayer()
        return await layer._run_fix_loop(
            ctx,
            gen_req,
            provider=None,
            model=None,
            code=code,
            scope=scope,
            assertions=assertions,
        )

    @pytest.mark.asyncio
    async def test_success_on_first_exec_no_fix(self):
        ctx = self._make_ctx()
        result, added_in, added_out = await self._run(ctx, [self._sbx(True)], gen_content="n/a")
        assert result.success
        assert added_in == 0 and added_out == 0
        assert ctx.scratch["code_fix_iterations"] == 0
        assert "code_fix_output" not in ctx.scratch

    @pytest.mark.asyncio
    async def test_fixes_broken_code(self):
        ctx = self._make_ctx()
        fixed = "```python\nx = 1\n```"
        result, added_in, added_out = await self._run(
            ctx,
            [self._sbx(False, error="NameError: name 'nope' is not defined"), self._sbx(True)],
            gen_content=fixed,
        )
        assert result.success
        assert ctx.scratch["code_fix_iterations"] == 1
        assert ctx.scratch["code_fix_output"] == fixed
        assert added_in > 0 and added_out > 0
        assert ctx.core.tools.invoke.await_count == 2
        assert ctx.core.llm.generate.await_count == 1
        # fix prompt must carry the original request + the sandbox error
        fix_prompt = ctx.core.llm.generate.await_args.args[0].prompt
        assert "write code" in fix_prompt
        assert "NameError" in fix_prompt

    @pytest.mark.asyncio
    async def test_exhausts_max_rounds(self):
        from more_core.layers.l0_execution import _MAX_CODE_FIX_ROUNDS

        ctx = self._make_ctx()
        always_fail = [self._sbx(False, error="boom")] * (_MAX_CODE_FIX_ROUNDS + 1)
        result, _, _ = await self._run(ctx, always_fail, gen_content="```python\nx = 1\n```")
        assert not result.success
        assert ctx.scratch["code_fix_iterations"] == _MAX_CODE_FIX_ROUNDS
        assert "code_fix_output" not in ctx.scratch
        assert ctx.core.llm.generate.await_count == _MAX_CODE_FIX_ROUNDS

    @pytest.mark.asyncio
    async def test_breaks_when_no_code_in_fix_output(self):
        ctx = self._make_ctx()
        result, _, _ = await self._run(
            ctx, [self._sbx(False, error="boom"), self._sbx(True)], gen_content="no fence here"
        )
        assert not result.success
        assert ctx.scratch["code_fix_iterations"] == 0
        assert ctx.core.tools.invoke.await_count == 1

    @pytest.mark.asyncio
    async def test_unsafe_fix_is_blocked(self):
        ctx = self._make_ctx()
        dangerous = "```python\nimport os\nos.system('rm -rf /')\n```"
        result, _, _ = await self._run(
            ctx, [self._sbx(False, error="boom"), self._sbx(True)], gen_content=dangerous
        )
        assert not result.success
        assert ctx.scratch.get("code_fix_blocked")
        assert ctx.core.tools.invoke.await_count == 1

    @pytest.mark.asyncio
    async def test_audit_writes_iteration_events(self):
        ctx = self._make_ctx()
        await self._run(
            ctx,
            [self._sbx(False, error="NameError: boom"), self._sbx(True)],
            gen_content="```python\nx = 1\n```",
        )
        calls = [
            c
            for c in ctx.core.audit.log.call_args_list
            if c.kwargs.get("action") == "code_fix_iteration"
        ]
        assert len(calls) == 2
        assert calls[0].kwargs["round"] == 0 and calls[0].kwargs["success"] is False
        assert calls[1].kwargs["round"] == 1 and calls[1].kwargs["success"] is True
        assert calls[1].kwargs["entity"] == "code"

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_crash(self):
        ctx = self._make_ctx()
        ctx.core.audit.log = MagicMock(side_effect=RuntimeError("audit down"))
        result, _, _ = await self._run(
            ctx,
            [self._sbx(False, error="boom"), self._sbx(True)],
            gen_content="```python\nx = 1\n```",
        )
        assert result.success

    # --- assertion-based behavioural verification (TDD-style) ------------

    @pytest.mark.asyncio
    async def test_assertions_reject_code_that_runs_but_fails(self):
        """Code that runs yet violates an acceptance assertion triggers a fix round."""
        ctx = self._make_ctx()
        result, _added_in, _added_out = await self._run(
            ctx,
            [self._sbx(False, error="AssertionError"), self._sbx(True)],
            gen_content="```python\nx = 2\n```",
            code="x = 1",
            assertions=["x == 2"],
        )
        assert result.success
        assert ctx.scratch["code_fix_iterations"] == 1
        assert ctx.scratch["code_verified"] is True
        assert ctx.core.tools.invoke.await_count == 2
        assert ctx.core.llm.generate.await_count == 1
        fix_prompt = ctx.core.llm.generate.await_args.args[0].prompt
        assert "AssertionError" in fix_prompt

    @pytest.mark.asyncio
    async def test_assertions_pass_without_extra_round(self):
        ctx = self._make_ctx()
        result, _added_in, _added_out = await self._run(
            ctx,
            [self._sbx(True)],
            gen_content="n/a",
            code="x = 1",
            assertions=["x == 1"],
        )
        assert result.success
        assert ctx.scratch["code_fix_iterations"] == 0
        assert ctx.scratch["code_verified"] is True
        assert ctx.core.tools.invoke.await_count == 1
        assert ctx.core.llm.generate.await_count == 0

    @pytest.mark.asyncio
    async def test_assertions_exhaust_rounds_on_stubborn_failure(self):
        ctx = self._make_ctx()
        always_fail = [self._sbx(False, error="AssertionError: x != 2")] * 4
        result, _, _ = await self._run(
            ctx,
            always_fail,
            gen_content="```python\nx = 1\n```",
            code="x = 1",
            assertions=["x == 2"],
        )
        assert not result.success
        assert "code_verified" not in ctx.scratch

    @pytest.mark.asyncio
    async def test_no_assertions_keeps_run_only_semantics(self):
        ctx = self._make_ctx()
        result, _, _ = await self._run(ctx, [self._sbx(True)], gen_content="n/a")
        assert result.success
        assert "code_verified" not in ctx.scratch
        assert ctx.core.tools.invoke.await_count == 1

    # --- deterministic repair + convergence guard (BPR D) ---------------

    @pytest.mark.asyncio
    async def test_deterministic_repair_avoids_llm_round(self):
        """Indentation error repaired statically → no LLM round is burned."""
        ctx = self._make_ctx()
        indented = "    print('hi')"
        result, added_in, added_out = await self._run(
            ctx,
            [self._sbx(False, error="IndentationError"), self._sbx(True)],
            gen_content="n/a",
            code=indented,
        )
        assert result.success
        assert ctx.scratch["code_fix_deterministic"] is True
        assert ctx.scratch["code_fix_iterations"] == 0
        assert added_in == 0 and added_out == 0
        assert ctx.core.tools.invoke.await_count == 2
        assert ctx.core.llm.generate.await_count == 0
        assert ctx.scratch["code_fix_output"] == "print('hi')"

    @pytest.mark.asyncio
    async def test_stops_early_on_stagnation(self):
        """Identical code + identical error for 2 rounds → early exit."""
        ctx = self._make_ctx()
        always_fail = [self._sbx(False, error="boom")] * 4
        result, _, _ = await self._run(
            ctx,
            always_fail,
            gen_content="```python\nx = 1\n```",
            code="x = 1",
        )
        assert not result.success
        assert ctx.scratch["code_fix_stagnant"] is True
        assert ctx.scratch["code_fix_iterations"] == 2
        assert ctx.core.llm.generate.await_count == 2
        assert ctx.core.tools.invoke.await_count == 3
        converged = [
            c
            for c in ctx.core.audit.log.call_args_list
            if c.kwargs.get("action") == "code_fix_converged"
        ]
        assert len(converged) == 1

    def test_deterministic_fix_leaves_valid_code_unchanged(self):
        assert ExecutionLayer._deterministic_fix("print('x')") == "print('x')"
        assert ExecutionLayer._deterministic_fix("x = 1\nprint(x)") == "x = 1\nprint(x)"

    def test_deterministic_fix_dedents_whole_block(self):
        code = "    def foo():\n        return 1\n"
        assert ExecutionLayer._deterministic_fix(code) == "def foo():\n    return 1"

    def test_deterministic_fix_trims_truncation(self):
        code = "x = 1\nprint(x\n"
        assert ExecutionLayer._deterministic_fix(code) == "x = 1"

    # --- best-of-k + differential validation (BPR A) ----------------------

    async def _run_k(
        self,
        ctx,
        gen_contents,
        invoke_results,
        *,
        k=2,
        scope="code",
        code="x = 1",
        assertions=None,
    ):
        from more_core.llm.provider import LLMRequest

        ctx.core.tools.invoke = AsyncMock(side_effect=invoke_results)
        ctx.core.llm.generate = AsyncMock(side_effect=[self._llm_response(c) for c in gen_contents])
        ctx.core.get_layer.side_effect = KeyError("L3 not found")
        ctx.core.audit.log = MagicMock()
        gen_req = LLMRequest(prompt="write code", system="sys", temperature=0.7, max_tokens=100)
        return await ExecutionLayer()._run_fix_loop(
            ctx,
            gen_req,
            provider=None,
            model=None,
            code=code,
            scope=scope,
            assertions=assertions,
            num_candidates=k,
        )

    @pytest.mark.asyncio
    async def test_best_of_k_picks_passing_candidate(self):
        """A failing first candidate does not burn a fix round when a sibling passes."""
        ctx = self._make_ctx()
        good = "```python\nprint('good')\n```"
        result, added_in, added_out = await self._run_k(
            ctx,
            ["```python\nprint(1 / 0)\n```", good],
            [self._sbx(False, error="ZeroDivisionError"), self._sbx(True)],
            code="print(1 / 0)",
        )
        assert result.success
        assert ctx.scratch["code_best_of_k"] is True
        assert ctx.scratch["code_fix_output"] == good
        assert ctx.scratch["code_fix_iterations"] == 0
        assert ctx.core.llm.generate.await_count == 2
        assert ctx.core.tools.invoke.await_count == 2
        assert added_in > 0 and added_out > 0

    @pytest.mark.asyncio
    async def test_best_of_k_differential_disagreement_enters_fix_loop(self):
        """Clean-but-disagreeing candidates are not trusted; the loop reconciles."""
        ctx = self._make_ctx()
        fixed = "```python\nprint('settled')\n```"
        result, _, _ = await self._run_k(
            ctx,
            ["```python\nprint('a')\n```", "```python\nprint('b')\n```", fixed],
            [
                ToolResult(tool="python_exec", success=True, output="output-A"),
                ToolResult(tool="python_exec", success=True, output="output-B"),
                ToolResult(tool="python_exec", success=True, output="settled"),
            ],
        )
        assert result.success
        assert ctx.scratch["code_best_of_k"] is True
        assert ctx.scratch["code_differential"] is True
        assert ctx.core.llm.generate.await_count == 3
        fix_prompt = ctx.core.llm.generate.await_args.args[0].prompt
        assert "differential" in fix_prompt

    @pytest.mark.asyncio
    async def test_best_of_k_no_usable_candidate_falls_back(self):
        """Candidates that yield no code fall back to the original single path."""
        ctx = self._make_ctx()
        fixed = "```python\ny = 2\n```"
        result, _, _ = await self._run_k(
            ctx,
            ["just prose", "more prose", fixed],
            [self._sbx(False, error="boom"), self._sbx(True)],
        )
        assert result.success
        assert ctx.scratch["code_best_of_k"] is True
        assert ctx.scratch["code_fix_output"] == fixed
        assert ctx.core.llm.generate.await_count == 3
        assert ctx.core.tools.invoke.await_count == 2

    def test_candidate_k_resolution(self):
        from more_core.layers.l0_execution import _MAX_CODE_CANDIDATES

        req = MagicMock()
        req.id = "k-res"
        req.type = TaskType.CODE_GENERATION
        req.context = {}
        core = MagicMock()
        core.settings = type("S", (), {"codegen_candidates": 2})()
        ctx = LayerContext(core=core, request=req)
        assert ExecutionLayer._candidate_k(ctx) == 2
        req.context = {"candidates": 99}
        assert ExecutionLayer._candidate_k(ctx) == _MAX_CODE_CANDIDATES
        req.context = {}
        core.settings = type("S", (), {"codegen_candidates": 1})()
        assert ExecutionLayer._candidate_k(ctx) == 1

    # --- multi-agent review gate (BPR C) ----------------------------------

    def _review_ctx(self, review_enabled: bool = True, query: str = "sum two numbers"):
        req = MagicMock()
        req.id = "review-test"
        req.type = TaskType.CODE_GENERATION
        req.context = {"review": review_enabled}
        req.query = query
        core = MagicMock()
        core.settings = type("S", (), {"codegen_review": review_enabled})()
        return LayerContext(core=core, request=req)

    async def _run_with_review(
        self,
        ctx,
        invoke_results,
        *,
        review_side_effect,
        code="x = 1",
        scope="code",
    ):
        from more_core.llm.provider import LLMRequest

        ctx.core.tools.invoke = AsyncMock(side_effect=invoke_results)
        ctx.core.llm.generate = AsyncMock(side_effect=review_side_effect)
        ctx.core.get_layer.side_effect = KeyError("L3 not found")
        ctx.core.audit.log = MagicMock()
        gen_req = LLMRequest(prompt="write code", system="sys", temperature=0.7, max_tokens=100)
        return await ExecutionLayer()._run_fix_loop(
            ctx,
            gen_req,
            provider=None,
            model=None,
            code=code,
            scope=scope,
        )

    def _review_gen(self, fix_content: str, reject_rounds: int = 1) -> Any:
        """LLM side-effect for the review-in-loop tests.

        Review prompts are recognised by the ``=== 评审者:`` banner.  The
        security reviewer rejects for the first *reject_rounds* panel passes,
        then every reviewer approves; any non-review prompt (a fix round)
        returns *fix_content*.
        """

        def _side_effect(request, *args, **kwargs):
            prompt = request.prompt
            if "=== 评审者:" in prompt:
                if "=== 评审者: security ===" in prompt and state["rejections"] < reject_rounds:
                    state["rejections"] += 1
                    return self._llm_response(
                        '{"verdict": "reject", "severity": "P1", '
                        '"findings": ["code evaluates untrusted input"], '
                        '"suggestion": "remove eval"}'
                    )
                return self._llm_response(
                    '{"verdict": "approve", "severity": "P3", "findings": []}'
                )
            return self._llm_response(fix_content)

        state = {"rejections": 0}
        return _side_effect

    @pytest.mark.asyncio
    async def test_review_rejection_feeds_fix_loop(self):
        """A P1 review finding turns a sandbox-green run into a fix round."""
        ctx = self._review_ctx()
        fixed = "```python\nx = 2\n```"
        result, added_in, added_out = await self._run_with_review(
            ctx,
            [self._sbx(True), self._sbx(True)],
            review_side_effect=self._review_gen(fixed),
        )
        assert result.success
        assert ctx.scratch["code_review"] is True
        assert ctx.scratch["code_review_rejected"] is True
        assert ctx.scratch["code_review_approved"] is True
        assert ctx.scratch["code_fix_iterations"] == 1
        assert ctx.scratch["code_fix_output"] == fixed
        assert ctx.core.llm.generate.await_count == 7  # 3 review + 1 fix + 3 review
        assert ctx.core.tools.invoke.await_count == 2
        assert added_in > 0 and added_out > 0
        fix_prompts = [
            c.args[0].prompt
            for c in ctx.core.llm.generate.call_args_list
            if "code review rejected" in c.args[0].prompt
        ]
        assert fix_prompts
        assert "code evaluates untrusted input" in fix_prompts[0]

    @pytest.mark.asyncio
    async def test_review_approved_passes_through(self):
        """Panel approval delivers the sandbox-green artifact without a fix round."""
        ctx = self._review_ctx()

        def _approve_all(request, *args, **kwargs):
            return self._llm_response('{"verdict": "approve", "severity": "P3", "findings": []}')

        result, added_in, added_out = await self._run_with_review(
            ctx,
            [self._sbx(True)],
            review_side_effect=_approve_all,
        )
        assert result.success
        assert ctx.scratch["code_review"] is True
        assert ctx.scratch["code_review_approved"] is True
        assert "code_review_rejected" not in ctx.scratch
        assert ctx.scratch["code_fix_iterations"] == 0
        assert ctx.core.llm.generate.await_count == 3
        assert ctx.core.tools.invoke.await_count == 1
        assert added_in > 0 and added_out > 0

    @pytest.mark.asyncio
    async def test_review_disabled_passes_through(self):
        """Default (review off) never invokes the panel."""
        ctx = self._review_ctx(review_enabled=False)
        result, added_in, added_out = await self._run_with_review(
            ctx,
            [self._sbx(True)],
            review_side_effect=self._review_gen("```python\nx = 2\n```"),
        )
        assert result.success
        assert "code_review" not in ctx.scratch
        assert ctx.core.llm.generate.await_count == 0
        assert ctx.core.tools.invoke.await_count == 1
        assert added_in == 0 and added_out == 0

    @pytest.mark.asyncio
    async def test_review_persistent_rejection_fails_closed(self):
        """Review keeps rejecting → the task is reported as failed, not delivered."""
        from more_core.layers.l0_execution import _MAX_CODE_FIX_ROUNDS

        ctx = self._review_ctx()

        def _reject_all(request, *args, **kwargs):
            if "=== 评审者:" in request.prompt:
                return self._llm_response(
                    '{"verdict": "reject", "severity": "P1", '
                    '"findings": ["unresolved design flaw"], "suggestion": "redesign"}'
                )
            return self._llm_response("```python\nx = 2\n```")

        result, _, _ = await self._run_with_review(
            ctx,
            [self._sbx(True)] * 4,
            review_side_effect=_reject_all,
        )
        assert not result.success
        assert ctx.scratch["code_review_rejected"] is True
        assert "code_fix_output" not in ctx.scratch
        assert ctx.scratch["code_fix_iterations"] == _MAX_CODE_FIX_ROUNDS

    def test_review_enabled_resolution(self):
        req = MagicMock()
        req.id = "review-res"
        req.type = TaskType.CODE_GENERATION
        req.context = {}
        core = MagicMock()
        core.settings = type("S", (), {"codegen_review": True})()
        ctx = LayerContext(core=core, request=req)
        assert ExecutionLayer._review_enabled(ctx) is True
        req.context = {"review": False}
        assert ExecutionLayer._review_enabled(ctx) is False
        core.settings = type("S", (), {"codegen_review": False})()
        req.context = {"review": True}
        assert ExecutionLayer._review_enabled(ctx) is True
        core.settings = type("S", (), {"codegen_review": False})()
        req.context = {}
        assert ExecutionLayer._review_enabled(ctx) is False


# =========================================================================
# Unit tests — _build_fix_prompt
# =========================================================================


class TestBuildFixPrompt:
    @pytest.mark.asyncio
    async def test_embeds_error_and_code(self):
        from more_core.layers.l0_execution import ExecutionLayer
        from more_core.llm.provider import LLMRequest
        from more_core.tools.registry import ToolResult

        req = LLMRequest(prompt="fix my code", system="sys", temperature=0.4, max_tokens=200)
        sbx = ToolResult(tool="python_exec", success=False, output="", error="TypeError: boom")
        prompt = ExecutionLayer._build_fix_prompt(req, "print('x')", sbx)
        assert "fix my code" in prompt
        assert "print('x')" in prompt
        assert "TypeError: boom" in prompt
        assert "代码执行失败" in prompt

    @pytest.mark.asyncio
    async def test_english_directive(self):
        from more_core.layers.l0_execution import ExecutionLayer
        from more_core.llm.provider import LLMRequest
        from more_core.tools.registry import ToolResult

        req = LLMRequest(
            prompt="write fibonacci in python", system="sys", temperature=0.4, max_tokens=200
        )
        sbx = ToolResult(tool="python_exec", success=False, output="", error="SyntaxError")
        prompt = ExecutionLayer._build_fix_prompt(req, "def f", sbx)
        assert "code fix enforcement" in prompt


# =========================================================================
# Integration tests
# =========================================================================


@pytest.mark.asyncio
class _CodeFakeLLMProvider:
    """返回**真实可执行代码**的假 provider。

    G1 交叉校验之后，"代码类任务 + 模型只返回文本"会被正确拦截
    （Controller verdict=escalated）。因此验证代码生成 happy path 的测试
    必须提供真的能跑通的代码，否则测的其实是旧契约。
    """

    name = "fake-code"

    async def generate(self, request):
        return LLMResponse(
            content='```python\nprint("hello from fake code")\n```',
            provider=self.name,
            model="fake-code-1",
            # token 数需达到真实量级：L0 的 thinking 预算守卫会拒绝
            # completion_tokens 过小（疑似空回答）的响应。
            prompt_tokens=100,
            completion_tokens=200,
            latency_ms=1.0,
        )

    async def health(self):
        return True

    def list_models(self):
        return ["fake-code-1"]

    async def close(self):
        return None


async def test_code_generation_extracts_and_runs(core) -> None:
    """L0 should detect code blocks in LLM output for CODE_GENERATION tasks."""
    core.llm._providers["fake-code"] = _CodeFakeLLMProvider()
    core.llm._fallback = ["fake-code"]
    req = TaskRequest(type=TaskType.CODE_GENERATION, query="print hello")
    result = await core.execute(req)
    assert result.status == TaskStatus.SUCCESS
    assert result.output


@pytest.mark.asyncio
async def test_tool_call_roundtrip(core) -> None:
    """L0 should handle <tool_call> XML in LLM output (tool dispatch path).

    The fake LLM does not produce tool_call tags, so this verifies the
    happy path completes without crashing when no tools are invoked.
    """
    req = TaskRequest(type=TaskType.NLP_TASK, query="search for info")
    result = await core.execute(req)
    assert result.status == TaskStatus.SUCCESS
    assert any(s.layer.value == "L0" for s in result.reasoning_chain)


@pytest.mark.asyncio
async def test_multiple_task_types_produce_output(core) -> None:
    """L0 should produce non-empty output for various task types."""
    core.llm._providers["fake-code"] = _CodeFakeLLMProvider()
    core.llm._fallback = ["fake-code"]
    for tt in (TaskType.CODE_DEBUGGING, TaskType.DATA_ANALYSIS, TaskType.MATH_REASONING):
        result = await core.execute(TaskRequest(type=tt, query="test"))
        assert result.status == TaskStatus.SUCCESS, f"failed for {tt}"
        assert result.output, f"empty output for {tt}"


class _FailingThenFixedProvider:
    """LLM provider that emits broken code first, then a fixed version.

    Mirrors a real LLM reacting to the sandbox error fed back by the fix loop.
    """

    name = "fixloop"

    def __init__(self) -> None:
        self._calls = 0

    async def generate(self, request):
        from more_core.llm.provider import LLMResponse

        self._calls += 1
        if self._calls == 1:
            content = "```python\nprint(1 / 0)\n```"
        else:
            content = "```python\nprint('fixed-ok')\n```"
        return LLMResponse(
            content=content,
            provider=self.name,
            model="fixloop-model",
            prompt_tokens=10,
            completion_tokens=256,
        )

    async def stream(self, request):
        yield "stream"

    async def health(self):
        return True


@pytest.mark.asyncio
async def test_fix_loop_end_to_end(core) -> None:
    """Broken generated code is executed, fails, gets fixed, and re-executes.

    The final L0 output must be the fixed code, and the description must
    mention the fix loop.
    """
    from more_core.tools.builtins import register_builtins

    register_builtins(core.tools, core)
    provider = _FailingThenFixedProvider()
    core.llm._providers[provider.name] = provider
    core.llm._fallback = [provider.name]

    req = TaskRequest(type=TaskType.CODE_GENERATION, query="print 1 divided by 0")
    result = await core.execute(req)

    assert provider._calls >= 2
    assert result.status == TaskStatus.SUCCESS
    assert "fixed-ok" in result.output
    l0_step = next(s for s in result.reasoning_chain if s.layer.value == "L0")
    assert "fix loop" in l0_step.description
    assert l0_step.confidence == 0.95
