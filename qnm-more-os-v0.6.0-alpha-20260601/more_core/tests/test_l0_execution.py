"""Tests for L0 execution layer — LLM generation + tool dispatch loop."""

from __future__ import annotations

import pytest

from more_core.core.types import TaskRequest, TaskStatus, TaskType


@pytest.mark.asyncio
async def test_code_generation_extracts_and_runs(core) -> None:
    """L0 should detect code blocks in LLM output for CODE_GENERATION tasks."""
    req = TaskRequest(type=TaskType.CODE_GENERATION, query="print hello")
    result = await core.execute(req)
    assert result.status == TaskStatus.SUCCESS
    assert result.output  # non-empty output from fake LLM


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
