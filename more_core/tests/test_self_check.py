"""Tests for the pipeline self-check (council/self_check.py).

Covers the text keyword-coverage path plus the code-task-aware branch that
treats a delivered code artifact as coverage.
"""

from __future__ import annotations

from types import SimpleNamespace

from more_core.core.types import LayerId, TaskType
from more_core.council.self_check import (
    _contains_code_artifact,
    run_pipeline_self_check,
)


def _steps(*descriptions: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(layer=LayerId.L4 if i % 2 == 0 else LayerId.L1, description=d)
        for i, d in enumerate(descriptions)
    ]


class TestTextSelfCheck:
    def test_keyword_coverage_used_for_text_tasks(self) -> None:
        steps = _steps("parsed task", "final answer with details")
        report = run_pipeline_self_check(steps, "the final answer")
        assert "coverage_pct" in report.to_dict()
        assert report.backfill_required

    def test_default_task_type_keeps_text_behaviour(self) -> None:
        steps = _steps("hello world")
        report = run_pipeline_self_check(steps, "hello world")
        assert report.coverage_pct == 100.0


class TestCodeSelfCheck:
    def test_code_task_with_fenced_artifact_is_fully_covered(self) -> None:
        steps = _steps("parsed task, difficulty=5", "strategy=balanced")
        report = run_pipeline_self_check(
            steps,
            "```python\nprint('hi')\n```",
            task_type=TaskType.CODE_GENERATION,
        )
        assert report.coverage_pct == 100.0
        assert not report.backfill_required
        assert report.overall_assessment == "代码产物完整"
        assert all(item["covered_in_final"] for item in report.completeness_check)

    def test_code_task_with_bare_compilable_code_is_covered(self) -> None:
        report = run_pipeline_self_check(
            _steps("planning"),
            "def add(a, b):\n    return a + b",
            task_type=TaskType.CODE_GENERATION,
        )
        assert report.coverage_pct == 100.0
        assert not report.backfill_required

    def test_code_task_without_code_is_uncovered_and_backfill(self) -> None:
        report = run_pipeline_self_check(
            _steps("planning", "strategy"),
            "抱歉，我无法生成代码。",
            task_type=TaskType.CODE_GENERATION,
        )
        assert report.coverage_pct == 0.0
        assert report.backfill_required
        assert report.backfill_items

    def test_debugging_task_uses_code_branch(self) -> None:
        report = run_pipeline_self_check(
            _steps("fix traceback"),
            "Traceback here\n```python\nx = fix()\n```",
            task_type=TaskType.CODE_DEBUGGING,
        )
        assert report.coverage_pct == 100.0


class TestContainsCodeArtifact:
    def test_fence_detected(self) -> None:
        assert _contains_code_artifact("text\n```python\nx = 1\n```")

    def test_bare_compilable_detected(self) -> None:
        assert _contains_code_artifact("def foo():\n    return 1")

    def test_prose_not_detected(self) -> None:
        assert not _contains_code_artifact("just a friendly answer")

    def test_empty_not_detected(self) -> None:
        assert not _contains_code_artifact("")
