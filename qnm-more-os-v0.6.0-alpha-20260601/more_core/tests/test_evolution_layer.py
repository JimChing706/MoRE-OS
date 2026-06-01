"""Integration tests for L2 EvolutionLayer + DGM evaluation loop."""

import pytest

from more_core.core.types import TaskRequest, TaskStatus, TaskType


@pytest.mark.asyncio
async def test_evolution_disabled_by_default(core) -> None:
    req = TaskRequest(type=TaskType.NLP_TASK, query="hello")
    result = await core.execute(req)
    assert result.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_benchmark_runner_wired(core) -> None:
    """BenchmarkRunner is set on DGMEngine after start()."""
    await core.start()
    try:
        assert core.evolution._runner is not None
        assert "simple" in core.benchmark_runner.list()
    finally:
        await core.stop()
