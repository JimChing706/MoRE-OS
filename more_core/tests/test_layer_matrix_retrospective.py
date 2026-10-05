"""分层综合测试矩阵 —— 回顾性检验（2026-10-05）。

**检验动机**：矩阵早期用例（X-I2/X-I3/X-I4）断言的是 ``core.router.route()``，
但 ``MoRECore`` 实际启用了 Meta-Orchestrator 谱路由，它会**完全覆盖**基座路由决策
（见 ``runtime/orchestrator.py``：``if self.meta_orchestrator is not None: decision = meta_decision``）。
即：**基座 LayerRouter 不是权威来源**，矩阵此前对"路由→执行"的断言存在假保障。

本文件把**权威契约**钉死：
1. 实际执行管道 == ``meta_orchestrator.route().pipeline``；
2. 每个执行层都在 ``metadata.stage_timings.layers_ms`` 留痕（D-4）；
3. L0 必然执行且位于末尾；执行层全部已注册；
4. VILLAGE 模式跳过 L3、RIVER 模式包含 L3（模式驱动，确定性）；
5. 显式登记"基座路由 ≠ 实际执行"这一已知分歧（防止静默漂移）。
"""

from __future__ import annotations

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskStatus, TaskType

# 低不确定度（VILLAGE）与高不确定度（RIVER）各取代表
_SAMPLE_TYPES = [
    TaskType.NLP_TASK,
    TaskType.CODE_GENERATION,
    TaskType.MULTI_AGENT_ORCHESTRATION,
    TaskType.ARCHITECTURE_DESIGN,
    TaskType.MATH_REASONING,
]


def _executed(result) -> list[str]:
    stages = (result.metadata or {}).get("stage_timings") or {}
    return list((stages.get("layers_ms") or {}).keys())


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", _SAMPLE_TYPES)
async def test_executed_pipeline_matches_meta_orchestrator(core, task_type):
    """权威契约：实际执行顺序 == Meta-Orchestrator 决策。"""
    req = TaskRequest(type=task_type, query="设计一个分布式系统架构")
    meta = core.meta_orchestrator.route(task_type, req.query, context=req.context)
    expected = [lid.value for lid in meta.pipeline]

    result = await core.execute(req)
    assert _executed(result) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", _SAMPLE_TYPES)
async def test_stage_timings_cover_every_executed_layer(core, task_type):
    """D-4 契约：每个执行层都要有分层耗时留痕，且 reasoning_chain 与之一致。"""
    result = await core.execute(TaskRequest(type=task_type, query="设计一个分布式系统架构"))
    executed = _executed(result)
    chain = [s.layer.value for s in (result.reasoning_chain or [])]
    assert executed, "分层耗时缺失"
    assert set(executed) == set(chain)


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", _SAMPLE_TYPES)
async def test_l0_always_runs_last_and_all_layers_registered(core, task_type):
    result = await core.execute(TaskRequest(type=task_type, query="设计一个分布式系统架构"))
    executed = _executed(result)

    assert executed, "管道不得为空"
    assert executed[-1] == LayerId.L0.value, "L0 必须是最后一个执行层"
    for lid in executed:
        assert core.get_layer(LayerId(lid)) is not None, f"执行了未注册层 {lid}"


def test_mode_determines_l3_inclusion(core):
    """L3 是否进入管道由谱模式（不确定性）决定，而非任务类型。

    VILLAGE(低 U) → 跳过 L3；RIVER(高 U) → 包含 L3。
    """
    simple = core.meta_orchestrator.route(TaskType.NLP_TASK, "你好")
    hard = core.meta_orchestrator.route(
        TaskType.ARCHITECTURE_DESIGN,
        "设计一个高并发分布式交易系统：一致性协议、容错恢复、分片路由、可观测性与性能优化，"
        "并给出权衡分析与风险清单",
    )
    assert LayerId.L3 not in simple.pipeline, "低不确定度应走轻量路径（无 L3）"
    assert LayerId.L3 in hard.pipeline, "高不确定度应走深度路径（含 L3）"


def test_base_router_diverges_from_authoritative_pipeline(core):
    """**已知分歧登记**：基座 LayerRouter 声明 ≠ 实际执行。

    ``MoRECore`` 启用 Meta-Orchestrator 后，``core.router.route()`` 的结果会被覆盖，
    因此矩阵中针对 ``core.router.route()`` 的断言只覆盖了非权威路径。此用例把分歧
    显式钉住：若将来两者对齐（或移除基座路由），该用例会失败并提醒更新矩阵/文档。
    """
    req = TaskRequest(type=TaskType.NLP_TASK, query="测试")
    base = [lid.value for lid in core.router.route(req).pipeline]
    meta = [lid.value for lid in core.meta_orchestrator.route(req.type, req.query).pipeline]

    assert base != meta, "基座路由与权威路由已对齐——请更新回顾性报告与矩阵文档"
    assert LayerId.L3.value in base and LayerId.L3.value not in meta


@pytest.mark.asyncio
async def test_self_improvement_without_monitoring_is_rejected_before_side_effect(core):
    """治理顺序：未显式要求元认知监控时，自改进被拒绝且**不得执行 L5/L2**。

    回归：若仅凭 allow_self_improvement 进入深度模式，L5/L2 会先执行自修改，
    随后才被 L3 的 policy.metacog_review 拒绝——"先自修改、后拒绝"不可接受。
    """
    core.settings.enable_evolution = True
    core.settings.enable_metacognition = True
    try:
        result = await core.execute(
            TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="自改进",
                        allow_self_improvement=True)
        )
        assert result.status == TaskStatus.REJECTED
        executed = _executed(result)
        assert LayerId.L2.value not in executed, "被治理拒绝前不得执行自修改"
        assert LayerId.L5.value not in executed
    finally:
        core.settings.enable_evolution = False
        core.settings.enable_metacognition = False


@pytest.mark.asyncio
async def test_deep_self_improvement_runs_l5_then_l2(core):
    """双开关齐备时，深度管道真正执行 L5 → L2（进化层可达）。"""
    core.settings.enable_evolution = True
    core.settings.enable_metacognition = True
    try:
        result = await core.execute(
            TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="自改进",
                        allow_self_improvement=True,
                        require_metacognitive_monitoring=True)
        )
        executed = _executed(result)
        assert executed[:2] == [LayerId.L5.value, LayerId.L2.value]
        assert result.status == TaskStatus.SUCCESS
    finally:
        core.settings.enable_evolution = False
        core.settings.enable_metacognition = False


# ---------------------------------------------------------------------------
# 建议 1：单一权威管道解析入口 resolve_pipeline()
# ---------------------------------------------------------------------------


def test_resolve_pipeline_prefers_meta_orchestrator(core):
    req = TaskRequest(type=TaskType.NLP_TASK, query="你好")
    decision, meta = core.resolve_pipeline(req)

    assert meta is not None
    assert decision.source == "meta_orchestrator"
    assert [lid.value for lid in decision.pipeline] == [lid.value for lid in meta.pipeline]


def test_resolve_pipeline_falls_back_to_router(core):
    """关闭谱路由后，基座 LayerRouter 成为 fallback 来源（source=router）。"""
    saved = core.meta_orchestrator
    core.meta_orchestrator = None
    try:
        req = TaskRequest(type=TaskType.NLP_TASK, query="你好")
        decision, meta = core.resolve_pipeline(req)
        assert meta is None
        assert decision.source == "router"
        assert decision.pipeline == core.router.route(req).pipeline
    finally:
        core.meta_orchestrator = saved


def test_routing_decision_default_source_is_router():
    from more_core.router.layer_router import RoutingDecision

    assert RoutingDecision(pipeline=[LayerId.L0], reasoning="x").source == "router"


@pytest.mark.asyncio
async def test_stream_and_execute_share_pipeline_source(core):
    """统一入口回归：流式曾始终走基座路由，与非流式管道不一致。"""
    import json

    req = TaskRequest(type=TaskType.NLP_TASK, query="统一管道")
    expected = [lid.value for lid in core.resolve_pipeline(req)[0].pipeline]

    layers: list[str] | None = None
    async for chunk in core.stream_execute(
        TaskRequest(type=TaskType.NLP_TASK, query="统一管道")
    ):
        if chunk.startswith("data: "):
            event = json.loads(chunk[len("data: "):].strip())
            if event.get("event") == "pipeline":
                layers = event.get("layers")
                break
    assert layers == expected, "流式管道必须与非流式同源"

    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="统一管道"))
    executed = _executed(result)
    assert executed == expected
