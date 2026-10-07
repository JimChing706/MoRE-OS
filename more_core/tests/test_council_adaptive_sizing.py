"""Council 降负载旋钮测试（重负载任务超预算的缓解）。

本地慢模型下 Council 默认 5 角色 × (独立+交叉) + 综合 ≈ 11 次 LLM 调用，
串行阶段会撑爆任务预算。此处固化两个降负载旋钮的契约：
``max_roles``（截断角色数）与 ``enable_cross_review``（关闭 Stage 2）。
"""

from __future__ import annotations

import pytest

from more_core.council.orchestrator import CouncilOrchestrator

_VALID = '{"summary": "ok", "confidence": 0.7, "consensus_level": "strong", "core_conclusion": "x"}'


@pytest.mark.asyncio
async def test_max_roles_truncates_council():
    calls: list[str] = []

    async def complete(prompt: str) -> str:
        calls.append(prompt)
        return _VALID

    council = CouncilOrchestrator(complete_fn=complete, max_roles=2)
    result = await council.deliberate("设计一个系统", mode="standard")

    assert len(result.independent_outputs) == 2
    assert [o["role"] for o in result.independent_outputs] == ["analyst", "architect"]


@pytest.mark.asyncio
async def test_cross_review_can_be_disabled():
    calls: list[str] = []

    async def complete(prompt: str) -> str:
        calls.append(prompt)
        return _VALID

    council = CouncilOrchestrator(complete_fn=complete, max_roles=2, enable_cross_review=False)
    result = await council.deliberate("设计一个系统", mode="standard")

    assert result.cross_review_outputs == []
    assert result.synthesis is not None
    # Stage1(2) + Stage2(0) + Stage3(1)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_default_behaviour_unchanged():
    """不传旋钮 → 维持原行为（5 角色 + 交叉审查 + 综合 = 11 次调用）。"""
    calls: list[str] = []

    async def complete(prompt: str) -> str:
        calls.append(prompt)
        return _VALID

    council = CouncilOrchestrator(complete_fn=complete)
    result = await council.deliberate("x")

    assert len(result.independent_outputs) == 5
    assert len(result.cross_review_outputs) == 5
    assert len(calls) == 11
