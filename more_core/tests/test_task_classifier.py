"""Tests for the zero-LLM NL → TaskType classifier."""

from __future__ import annotations

import pytest

from more_core.core.types import TaskType
from more_core.router.task_classifier import classify, classify_task_type


class TestKeywordClassification:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("开发电话拨号程序APP", TaskType.CODE_GENERATION),
            ("请生成一个 Python 排序算法代码", TaskType.CODE_GENERATION),
            ("write a function that parses CSV", TaskType.CODE_GENERATION),
            ("implement a fibonacci function", TaskType.CODE_GENERATION),
            ("这个函数报错了，帮我修复", TaskType.CODE_DEBUGGING),
            ("fix the bug in the login module", TaskType.CODE_DEBUGGING),
            ("请审查这段代码的安全性", TaskType.CODE_REVIEW),
            ("code review the pull request", TaskType.CODE_REVIEW),
            ("为这个模块编写单元测试", TaskType.CODE_TESTING),
            ("write unit tests for the parser", TaskType.CODE_TESTING),
            ("证明哥德巴赫猜想", TaskType.MATH_REASONING),
            ("prove that sqrt(2) is irrational", TaskType.MATH_REASONING),
            ("分析这份销售数据并出报表", TaskType.DATA_ANALYSIS),
            ("analyze the dataset statistics", TaskType.DATA_ANALYSIS),
            ("设计一个微服务系统架构", TaskType.ARCHITECTURE_DESIGN),
            ("design the system architecture", TaskType.ARCHITECTURE_DESIGN),
            ("编排多个智能体协作完成任务", TaskType.MULTI_AGENT_ORCHESTRATION),
            ("orchestrate a multi-agent workflow", TaskType.MULTI_AGENT_ORCHESTRATION),
            ("如何实现自我改进学习策略", TaskType.SELF_IMPROVEMENT),
            ("self-improvement strategy", TaskType.SELF_IMPROVEMENT),
            ("将模型迁移到新领域", TaskType.CROSS_DOMAIN_TRANSFER),
            ("transfer learning to a new domain", TaskType.CROSS_DOMAIN_TRANSFER),
        ],
    )
    def test_classify_returns_expected_type(self, query: str, expected: TaskType) -> None:
        assert classify_task_type(query) == expected

    @pytest.mark.parametrize(
        "query",
        [
            "你好",
            "今天天气怎么样",
            "random sentence with no signal",
            "tell me a joke",
        ],
    )
    def test_classify_falls_back_to_nlp(self, query: str) -> None:
        assert classify_task_type(query) == TaskType.NLP_TASK

    def test_never_returns_auto(self) -> None:
        result = classify("any query")
        assert result.task_type is not TaskType.AUTO


class TestConfidence:
    def test_strong_signal_gets_high_confidence(self) -> None:
        result = classify("请生成一个 Python 排序算法代码")
        assert result.confidence >= 0.6

    def test_confidence_bounded_by_max(self) -> None:
        result = classify("写一个代码生成程序 生成代码 编写函数")
        assert result.confidence <= 0.95

    def test_nlp_fallback_confidence_is_0_5(self) -> None:
        result = classify("今天天气怎么样")
        assert result.confidence == 0.5
        assert result.task_type == TaskType.NLP_TASK

    def test_matched_keywords_are_reported(self) -> None:
        result = classify("fix the bug in the login module")
        assert result.task_type == TaskType.CODE_DEBUGGING
        assert "bug" in result.matched_keywords


class TestDeterminism:
    def test_same_query_same_result(self) -> None:
        q = "开发电话拨号程序APP"
        assert classify(q) == classify(q)

    def test_case_insensitive_english(self) -> None:
        assert classify_task_type("WRITE A FUNCTION to add") == TaskType.CODE_GENERATION
        assert classify_task_type("write a FUNCTION to add") == TaskType.CODE_GENERATION
