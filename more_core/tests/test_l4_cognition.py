"""Tests for L4 — Cognition Layer (task parsing, planning, difficulty estimation)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.core.types import LayerId, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l4_cognition import (
    CognitionLayer,
    _DIFFICULTY_BASE,
    _estimate_complexity_bonus,
)


def _make_ctx(
    task_type: TaskType = TaskType.CODE_GENERATION,
    query: str = "build a simple app",
    providers: list[str] | None = None,
    has_llm: bool = True,
    has_output_filter: bool = True,
    has_planner: bool = True,
) -> LayerContext:
    core = MagicMock()
    core.settings = MagicMock()

    if has_llm:
        llm = MagicMock()
        llm.list_providers.return_value = providers or ["mock"]
        llm.generate = AsyncMock()
        llm.generate.return_value = MagicMock(content="")
        core.llm = llm
    else:
        core.llm = None

    core.output_filter = MagicMock() if has_output_filter else None
    if has_output_filter:
        core.output_filter.filter.side_effect = lambda s: s

    core.council_orchestrator = None

    if has_planner:
        core.planner = MagicMock()
        core.planner.create_plan.return_value = MagicMock(id="plan-123")
        core.planner.validate_plan.return_value = []
    else:
        core.planner = None

    req = MagicMock()
    req.type = task_type
    req.query = query
    req.context = {}
    req.id = "test-l4-task"

    ctx = LayerContext(core=core, request=req)
    ctx.scratch = {}
    return ctx


class TestDifficultyEstimation:

    @pytest.mark.asyncio
    async def test_base_difficulty_by_task_type(self):
        for task_type, expected_base in _DIFFICULTY_BASE.items():
            ctx = _make_ctx(task_type=task_type, query="short query")
            await CognitionLayer().process(ctx)
            assert ctx.scratch["difficulty"] >= expected_base, (
                f"{task_type} base >= {expected_base}"
            )

    @pytest.mark.asyncio
    async def test_length_bonus_capped_at_plus_3(self):
        ctx = _make_ctx(query="A" * 2000)
        await CognitionLayer().process(ctx)
        base = _DIFFICULTY_BASE[TaskType.CODE_GENERATION]
        assert ctx.scratch["difficulty"] <= base + 3 + 4

    def test_complexity_bonus_english_keyword(self):
        bonus = _estimate_complexity_bonus("need to integrate distributed system")
        assert bonus >= 2

    def test_complexity_bonus_chinese_keyword(self):
        bonus = _estimate_complexity_bonus("需要集成分布式架构")
        assert bonus >= 2

    def test_complexity_bonus_code_keywords(self):
        bonus = _estimate_complexity_bonus(
            "full-stack crud rest api with database auth deploy"
        )
        assert bonus >= 1  # at least one keyword matched, capped at 4

    def test_complexity_bonus_no_keywords(self):
        bonus = _estimate_complexity_bonus("hello world simple task")
        assert bonus == 0

    def test_complexity_bonus_capped_at_4(self):
        bonus = _estimate_complexity_bonus(
            "integrate distributed concurrent optimize "
            "full-stack crud rest api database auth deploy "
            "pipeline microservice websocket queue cache"
        )
        assert bonus <= 4

    @pytest.mark.asyncio
    async def test_difficulty_total_capped_at_10(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="full-stack crud distributed microservice " * 50,
        )
        await CognitionLayer().process(ctx)
        assert ctx.scratch["difficulty"] <= 10


class TestCapabilityEstimation:

    @pytest.mark.asyncio
    async def test_no_providers_defaults_to_7(self):
        ctx = _make_ctx(providers=[])
        await CognitionLayer().process(ctx)
        assert ctx.scratch["capability"] == 7

    @pytest.mark.asyncio
    async def test_one_provider_gives_7(self):
        ctx = _make_ctx(providers=["mock"])
        await CognitionLayer().process(ctx)
        assert ctx.scratch["capability"] == 7

    @pytest.mark.asyncio
    async def test_three_providers_gives_9(self):
        ctx = _make_ctx(providers=["a", "b", "c"])
        await CognitionLayer().process(ctx)
        assert ctx.scratch["capability"] == 9

    @pytest.mark.asyncio
    async def test_four_providers_capped_at_10(self):
        ctx = _make_ctx(providers=["a", "b", "c", "d"])
        await CognitionLayer().process(ctx)
        assert ctx.scratch["capability"] == 10


class TestDecompositionThreshold:

    @pytest.mark.asyncio
    async def test_low_difficulty_no_llm_decomposition(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="hi")
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is False
        assert plan["subtasks"] == ["hi"]

    @pytest.mark.asyncio
    async def test_high_difficulty_triggers_llm_decomposition(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="optimize distributed architecture",
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["step 1", "step 2"]</subtasks>'
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is True
        assert len(plan["subtasks"]) == 2


class TestLLMDecomposition:

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
        )
        ctx.core.llm.generate = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is False
        assert plan["subtasks"] == ["complex task"]

    @pytest.mark.asyncio
    async def test_fallback_on_single_subtask(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["only one"]</subtasks>'
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is False

    @pytest.mark.asyncio
    async def test_fallback_on_empty_subtasks(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content="<subtasks>[]</subtasks>"
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is False

    @pytest.mark.asyncio
    async def test_no_llm_available_skips_decomposition(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_llm=False,
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["decomposed"] is False

    @pytest.mark.asyncio
    async def test_output_filter_applied_to_subtasks(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_output_filter=True,
        )
        ctx.core.output_filter.filter = MagicMock(
            side_effect=lambda s: f"safe:{s}"
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["step 1", "step 2"]</subtasks>'
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert "safe:step 1" in plan["subtasks"]

    @pytest.mark.asyncio
    async def test_no_output_filter_does_not_crash(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_output_filter=False,
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["step 1", "step 2"]</subtasks>'
        )
        result = await CognitionLayer().process(ctx)
        assert result.layer == LayerId.L4

    @pytest.mark.asyncio
    async def test_difficulty_adjusted_by_subtask_count(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["s1", "s2", "s3", "s4", "s5"]</subtasks>'
        )
        await CognitionLayer().process(ctx)
        plan = ctx.scratch["plan"]
        assert plan["difficulty"] > _DIFFICULTY_BASE[TaskType.SELF_IMPROVEMENT]


class TestConfidence:

    @pytest.mark.asyncio
    async def test_not_decomposed(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="simple")
        result = await CognitionLayer().process(ctx)
        assert result.confidence == 0.88

    @pytest.mark.asyncio
    async def test_decomposed(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["s1", "s2", "s3"]</subtasks>'
        )
        result = await CognitionLayer().process(ctx)
        assert result.confidence == 0.92


class TestPlanIntegration:

    @pytest.mark.asyncio
    async def test_plan_created_when_decomposed(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_planner=True,
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["s1", "s2"]</subtasks>'
        )
        await CognitionLayer().process(ctx)
        ctx.core.planner.create_plan.assert_called_once()
        ctx.core.planner.validate_plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_failure_does_not_block(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_planner=True,
        )
        ctx.core.planner.create_plan.return_value = MagicMock(id="plan-123")
        ctx.core.planner.validate_plan.return_value = ["issue"]
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["s1", "s2"]</subtasks>'
        )
        result = await CognitionLayer().process(ctx)
        assert result.layer == LayerId.L4

    @pytest.mark.asyncio
    async def test_no_planner_skips_gracefully(self):
        ctx = _make_ctx(
            task_type=TaskType.SELF_IMPROVEMENT,
            query="complex task",
            has_planner=False,
        )
        ctx.core.llm.generate = AsyncMock()
        ctx.core.llm.generate.return_value = MagicMock(
            content='<subtasks>["s1", "s2"]</subtasks>'
        )
        result = await CognitionLayer().process(ctx)
        assert result.layer == LayerId.L4


class TestStructuredPlanIntegration:

    @pytest.mark.asyncio
    async def test_structured_plan_in_scratch(self):
        mock_structured = MagicMock()
        mock_structured.to_dict.return_value = {"phases": [{"name": "phase1"}]}
        with patch(
            "more_core.planning.structured_plan.merge_plan_with_l4_output",
            return_value=mock_structured,
        ):
            ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="simple")
            await CognitionLayer().process(ctx)
            assert ctx.scratch["structured_plan"] == {"phases": [{"name": "phase1"}]}

    @pytest.mark.asyncio
    async def test_structured_plan_none_when_merge_fails(self):
        with patch(
            "more_core.planning.structured_plan.merge_plan_with_l4_output",
            return_value=None,
        ):
            ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="simple")
            result = await CognitionLayer().process(ctx)
            assert result.layer == LayerId.L4


class TestParseSubtasks:

    def setup_method(self) -> None:
        self.layer = CognitionLayer()

    def test_xml_tags(self):
        result = self.layer._parse_subtasks(
            '<subtasks>["task 1", "task 2"]</subtasks>'
        )
        assert result == ["task 1", "task 2"]

    def test_json_code_fence(self):
        result = self.layer._parse_subtasks(
            '```json\n["task 1", "task 2"]\n```'
        )
        assert result == ["task 1", "task 2"]

    def test_no_markers_returns_empty(self):
        result = self.layer._parse_subtasks("just plain text")
        assert result == []

    def test_empty_content_returns_empty(self):
        result = self.layer._parse_subtasks("")
        assert result == []

    def test_invalid_json_returns_empty(self):
        result = self.layer._parse_subtasks(
            "<subtasks>[invalid json here]</subtasks>"
        )
        assert result == []

    def test_not_a_list_returns_empty(self):
        result = self.layer._parse_subtasks(
            "<subtasks>\"just a string\"</subtasks>"
        )
        assert result == []

    def test_list_with_non_strings_returns_empty(self):
        result = self.layer._parse_subtasks(
            "<subtasks>[1, 2, 3]</subtasks>"
        )
        assert result == []

    def test_xml_with_newlines_and_spaces(self):
        result = self.layer._parse_subtasks(
            "<subtasks>\n  [\"a\", \"b\"]\n</subtasks>"
        )
        assert result == ["a", "b"]


class TestBuildDecomposePrompt:

    def setup_method(self) -> None:
        self.layer = CognitionLayer()

    def _make_minimal_ctx(self, task_type: TaskType, query: str) -> LayerContext:
        core = MagicMock()
        req = MagicMock()
        req.type = task_type
        req.query = query
        req.context = {}
        return LayerContext(core=core, request=req)

    def test_cjk_code_contains_code_guide(self):
        ctx = self._make_minimal_ctx(TaskType.CODE_GENERATION, "写代码")
        with patch(
            "more_core.core.unicode_utils.is_predominantly_cjk",
            return_value=True,
        ):
            prompt = self.layer._build_decompose_prompt(ctx)
        assert "数据模型" in prompt
        assert "子任务" in prompt

    def test_cjk_non_code_contains_independence(self):
        ctx = self._make_minimal_ctx(TaskType.NLP_TASK, "写文章")
        with patch(
            "more_core.core.unicode_utils.is_predominantly_cjk",
            return_value=True,
        ):
            prompt = self.layer._build_decompose_prompt(ctx)
        assert "独立性" in prompt
        assert "子任务" in prompt

    def test_english_code_contains_data_model(self):
        ctx = self._make_minimal_ctx(TaskType.CODE_GENERATION, "Build an API")
        with patch(
            "more_core.core.unicode_utils.is_predominantly_cjk",
            return_value=False,
        ):
            prompt = self.layer._build_decompose_prompt(ctx)
        assert "Data model" in prompt
        assert "subtask" in prompt.lower()

    def test_english_non_code_no_data_model(self):
        ctx = self._make_minimal_ctx(TaskType.NLP_TASK, "Write a blog")
        with patch(
            "more_core.core.unicode_utils.is_predominantly_cjk",
            return_value=False,
        ):
            prompt = self.layer._build_decompose_prompt(ctx)
        assert "Data model" not in prompt
        assert "subtask" in prompt.lower()

    def test_prompt_contains_task_type_value(self):
        ctx = self._make_minimal_ctx(TaskType.CODE_GENERATION, "test")
        with patch(
            "more_core.core.unicode_utils.is_predominantly_cjk",
            return_value=False,
        ):
            prompt = self.layer._build_decompose_prompt(ctx)
        assert TaskType.CODE_GENERATION.value in prompt


class TestDescription:

    @pytest.mark.asyncio
    async def test_contains_difficulty_and_capability(self):
        ctx = _make_ctx(task_type=TaskType.CODE_GENERATION, query="build api")
        result = await CognitionLayer().process(ctx)
        assert "difficulty" in result.description
        assert "capability" in result.description

    @pytest.mark.asyncio
    async def test_layer_id(self):
        assert CognitionLayer().layer_id == LayerId.L4

    @pytest.mark.asyncio
    async def test_output_contains_plan(self):
        ctx = _make_ctx(task_type=TaskType.NLP_TASK, query="simple")
        result = await CognitionLayer().process(ctx)
        assert "subtasks" in result.output
        assert "difficulty" in result.output
