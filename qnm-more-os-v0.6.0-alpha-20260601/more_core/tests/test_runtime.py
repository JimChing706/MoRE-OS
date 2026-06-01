import pytest

from more_core.core.types import TaskRequest, TaskStatus, TaskType


@pytest.mark.asyncio
async def test_execute_nlp_task_succeeds(core) -> None:
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="hello"))
    assert result.status == TaskStatus.SUCCESS
    assert "fake-reply" in result.output
    assert any(step.layer.value == "L0" for step in result.reasoning_chain)


@pytest.mark.asyncio
async def test_governance_blocks_self_improvement_when_meta_disabled(core) -> None:
    req = TaskRequest(
        type=TaskType.SELF_IMPROVEMENT, query="improve yourself", allow_self_improvement=True
    )
    result = await core.execute(req)
    assert result.status == TaskStatus.REJECTED


@pytest.mark.asyncio
async def test_memory_store_tracks_entries(core) -> None:
    from more_core.memory.store import MemoryEntry, MemoryKind

    core.memory.put(MemoryEntry(content="hello world", kind=MemoryKind.EPISODIC))
    assert core.memory.stats()["episodic"] == 1
