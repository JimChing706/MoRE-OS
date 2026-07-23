"""Tests for L0 execution layer — LLM generation + tool dispatch loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskStatus, TaskType
from more_core.layers.l0_execution import (
    ExecutionLayer,
    _extract_llm_confidence,
)
from more_core.layers.base import LayerContext


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
        code = 'x = 1'
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


# =========================================================================
# Unit tests — _extract_test_code
# =========================================================================


class TestExtractTestCode:
    def setup_method(self) -> None:
        self._method = staticmethod(ExecutionLayer._extract_test_code).__func__

    def test_extract_python_test_fence(self):
        code = 'def test_hello(): pass'
        text = f"```python test\n{code}\n```"
        assert self._method(text) == code

    def test_extract_python_pytest_fence(self):
        code = 'def test_foo(): assert 1'
        text = f"```python pytest\n{code}\n```"
        assert self._method(text) == code

    def test_extract_python_unittest_fence(self):
        code = 'class TestFoo(unittest.TestCase): pass'
        text = f"```python unittest\n{code}\n```"
        assert self._method(text) == code

    def test_fallback_to_python_fence_with_test_keyword(self):
        code = 'def test_something(): assert True'
        text = f"```python\n{code}\n```"
        assert self._method(text) == code

    def test_fallback_with_pytest_import(self):
        code = 'import pytest\ndef test_x(): pass'
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
        safe, violations = ExecutionLayer._check_code_safety("eval('x')", ctx)
        assert safe is False

    def test_dangerous_exec_detected(self):
        ctx = self._make_ctx()
        safe, violations = ExecutionLayer._check_code_safety("exec('x')", ctx)
        assert safe is False

    def test_dangerous_subprocess_call_detected(self):
        ctx = self._make_ctx()
        safe, violations = ExecutionLayer._check_code_safety("subprocess.call('ls')", ctx)
        assert safe is False

    def test_fallback_when_l3_unavailable(self):
        ctx = self._make_ctx(l3_available=False)
        safe, violations = ExecutionLayer._check_code_safety("eval('danger')", ctx)
        assert safe is False

    def test_safe_code_when_l3_unavailable(self):
        ctx = self._make_ctx(l3_available=False)
        safe, violations = ExecutionLayer._check_code_safety("print('ok')", ctx)
        assert safe is True

    def test_l3_without_rule_engine_falls_back(self):
        ctx = self._make_ctx(l3_available=True, l3_has_rule_engine=False)
        safe, violations = ExecutionLayer._check_code_safety("print('ok')", ctx)
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
# Integration tests
# =========================================================================


@pytest.mark.asyncio
async def test_code_generation_extracts_and_runs(core) -> None:
    """L0 should detect code blocks in LLM output for CODE_GENERATION tasks."""
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
    for tt in (TaskType.CODE_DEBUGGING, TaskType.DATA_ANALYSIS, TaskType.MATH_REASONING):
        result = await core.execute(TaskRequest(type=tt, query="test"))
        assert result.status == TaskStatus.SUCCESS, f"failed for {tt}"
        assert result.output, f"empty output for {tt}"
