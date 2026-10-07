"""分层架构综合测试矩阵（L0–L5）。

设计书: docs/audits/LAYER_TEST_MATRIX_2026-10-05.md
覆盖六个维度: 契约(C) / 正常流(H) / 边界(B) / 异常降级(E) / 治理门控(G) / 集成(I)

约定：所有用例离线可跑（复用 conftest 的 core fixture：已注册内置工具 + 假 LLM）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from more_core.core.types import LayerId, TaskRequest, TaskStatus, TaskType
from more_core.layers.base import LayerContext, LayerResult

# 整个矩阵纳入 CI 门禁（PR 必跑）
pytestmark = pytest.mark.layer_matrix

# ===========================================================================
# 通用契约矩阵（L-C1 .. L-C5）—— 六层通用
# ===========================================================================

ALL_LAYERS = [LayerId.L0, LayerId.L1, LayerId.L2, LayerId.L3, LayerId.L4, LayerId.L5]


@pytest.mark.parametrize("lid", ALL_LAYERS)
def test_layer_contract_id_matches_registry(core, lid):
    """L-C2: 每层 layer_id 与注册表一致。"""
    layer = core.get_layer(lid)
    assert layer.layer_id == lid


@pytest.mark.parametrize("lid", ALL_LAYERS)
@pytest.mark.asyncio
async def test_layer_run_returns_layer_result(core, lid):
    """L-C3/L-C4: run() 返回 LayerResult 并追加 ReasoningStep。"""
    layer = core.get_layer(lid)
    ctx = LayerContext(
        core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="hello"), user_id="tester"
    )
    before = len(ctx.accumulated_steps)
    result = await layer.run(ctx)

    assert isinstance(result, LayerResult)
    assert result.layer == lid
    assert len(ctx.accumulated_steps) == before + 1
    assert ctx.accumulated_steps[-1].duration_ms >= 0
    assert result.duration_ms >= 0


def test_all_six_layers_registered(core):
    """L-C5 / X-I1: 六层全部注册且无重复。"""
    registered = [lid for lid in ALL_LAYERS if core.get_layer(lid) is not None]
    assert registered == ALL_LAYERS
    ids = [core.get_layer(lid).layer_id for lid in ALL_LAYERS]
    assert len(set(ids)) == len(ids)


# ===========================================================================
# L0 执行层
# ===========================================================================


@pytest.mark.asyncio
async def test_l0_h1_plain_task_produces_output(core):
    """L0-H1: 纯文本任务产出非空。"""
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="say hello"))
    assert result.status == TaskStatus.SUCCESS
    assert str(result.output).strip()


@pytest.mark.asyncio
async def test_l0_b1_very_long_query_does_not_crash(core):
    """L0-B1: 超长 query 不崩溃。"""
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="x" * 5000))
    assert result.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.REJECTED)
    assert result.output is not None


@pytest.mark.asyncio
async def test_l0_e1_llm_failure_is_structured(core):
    """L0-E1: LLM 全失败 → 结构化失败（不抛裸异常）。"""
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider(inject_errors=True)
    core.llm._fallback = ["fake"]

    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="will fail"))
    assert result.status == TaskStatus.FAILED
    assert str(result.output).strip(), "失败必须给出原因，不能空输出"


def _install_code_provider(core, content: str):
    """把返回指定代码块的假 provider 装进 core（无网络、可重复）。"""
    from more_core.llm.provider import LLMResponse

    class _CodeProvider:
        name = "fake"

        async def generate(self, request):  # noqa: ANN001
            return LLMResponse(
                content=content,
                provider="fake",
                model="fake-code-1",
                prompt_tokens=100,
                completion_tokens=200,
                latency_ms=1.0,
            )

        async def stream(self, request):  # noqa: ANN001
            yield content

        async def health(self):
            return True

    core.llm._providers["fake"] = _CodeProvider()
    core.llm._fallback = ["fake"]


@pytest.mark.asyncio
async def test_l0_h2_code_task_extracts_and_runs_code(core):
    """L0-H2: 代码任务从 LLM 输出提取代码块并进沙箱，结果非静默。"""
    _install_code_provider(core, '```python\nprint("hello from test")\n```')
    result = await core.execute(
        TaskRequest(type=TaskType.CODE_GENERATION, query="写一个打印 hello 的程序")
    )
    assert result.status in (TaskStatus.SUCCESS, TaskStatus.FAILED)
    assert str(result.output).strip(), "代码任务不得返回空产出"
    # 代码类任务必须留下交付闸门报告（产出正确性链路闭环）
    gates = (result.metadata or {}).get("delivery_gates")
    assert gates is not None, "代码任务缺少 delivery_gates 元数据"


@pytest.mark.asyncio
async def test_l0_g1_broken_code_blocked_by_gate(core):
    """L0-G1: 语法错误的生成代码被交付闸门拦截，状态降级为 FAILED。"""
    _install_code_provider(core, "```python\ndef broken(:\n    pass\n```")
    result = await core.execute(
        TaskRequest(type=TaskType.CODE_GENERATION, query="写一个正确的函数")
    )
    gates = (result.metadata or {}).get("delivery_gates")
    assert gates is not None, "代码任务缺少 delivery_gates 元数据"
    assert gates["passed"] is False, "语法错误代码必须被闸门拦截"
    assert result.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_l0_i1_stage_timings_recorded(core):
    """L0-I1: 阶段耗时写入 metadata（D-4 契约）。"""
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    stages = (result.metadata or {}).get("stage_timings") or {}
    assert "layers_ms" in stages
    assert LayerId.L0.value in stages["layers_ms"]


# ===========================================================================
# L1 编排层 —— OMAC 4-tuple 强契约
# ===========================================================================


def _omac(**over):
    base = {
        "mode": "autonomous",
        "strategy": "balanced",
        "model_hint": "standard",
        "token_budget": 4096,
    }
    base.update(over)
    return base


def test_l1_c1_valid_omac_tuple(core):
    layer = core.get_layer(LayerId.L1)
    ok, reason = layer._validate_omac_output(_omac())
    assert ok is True, reason


@pytest.mark.parametrize("missing", ["mode", "strategy", "model_hint", "token_budget"])
def test_l1_c2_missing_key_rejected(core, missing):
    layer = core.get_layer(LayerId.L1)
    data = _omac()
    del data[missing]
    ok, reason = layer._validate_omac_output(data)
    assert ok is False and "missing key" in reason


@pytest.mark.parametrize("bad", [True, False, "4096", 3.5, None])
def test_l1_c3_token_budget_type_rejected(core, bad):
    layer = core.get_layer(LayerId.L1)
    ok, reason = layer._validate_omac_output(_omac(token_budget=bad))
    assert ok is False, f"token_budget={bad!r} 应被拒绝"


@pytest.mark.parametrize("bad", [0, -1])
def test_l1_c4_token_budget_must_be_positive(core, bad):
    layer = core.get_layer(LayerId.L1)
    ok, _ = layer._validate_omac_output(_omac(token_budget=bad))
    assert ok is False


@pytest.mark.parametrize(
    "field,bad",
    [("mode", "turbo"), ("strategy", "nonsense"), ("model_hint", "quantum")],
)
def test_l1_c5_invalid_enum_values_rejected(core, field, bad):
    layer = core.get_layer(LayerId.L1)
    ok, _ = layer._validate_omac_output(_omac(**{field: bad}))
    assert ok is False


def test_l1_c6_non_dict_rejected(core):
    layer = core.get_layer(LayerId.L1)
    ok, _ = layer._validate_omac_output(["not", "a", "dict"])
    assert ok is False


@pytest.mark.asyncio
async def test_l1_h1_produces_strategy_for_downstream(core):
    """L1-H1/I1: 正常任务产出策略参数供 L0 消费。"""
    layer = core.get_layer(LayerId.L1)
    ctx = LayerContext(
        core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="写代码")
    )
    result = await layer.run(ctx)
    assert result.output is not None
    assert isinstance(ctx.scratch.get("temperature", 0.0), (int, float))
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_l1_b1_unknown_task_type_has_default_policy(core):
    """L1-B1: 未映射的任务类型仍产出默认策略（不崩溃）。"""
    layer = core.get_layer(LayerId.L1)
    req = TaskRequest(type=TaskType.AUTO, query="模糊任务")
    ctx = LayerContext(core=core, request=req)
    result = await layer.run(ctx)
    assert result.layer == LayerId.L1
    assert result.output is not None


# ===========================================================================
# L2 进化层 —— 双重门控
# ===========================================================================


@pytest.mark.asyncio
async def test_l2_g1_disabled_by_default(core):
    """L2-G1: 默认关闭 → evolved=False 且说明含 disabled。"""
    layer = core.get_layer(LayerId.L2)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="改进"))
    result = await layer.run(ctx)
    assert result.output["evolved"] is False
    assert "disabled" in result.description.lower()


@pytest.mark.asyncio
async def test_l2_g2_requires_request_opt_in(core):
    """L2-G2: 全局开但 request 未允许 → 仍禁用（双重门控）。"""
    core.settings.enable_evolution = True
    layer = core.get_layer(LayerId.L2)
    req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="改进", allow_self_improvement=False)
    result = await layer.run(LayerContext(core=core, request=req))
    assert result.output["evolved"] is False
    core.settings.enable_evolution = False


@pytest.mark.asyncio
async def test_l2_i1_disabled_path_does_not_touch_dgm(core):
    """L2-I1: 门控关闭时不得调用 DGM.snapshot（避免副作用）。"""
    layer = core.get_layer(LayerId.L2)
    fake_dgm = MagicMock()
    fake_dgm.snapshot = AsyncMock()
    core.evolution = fake_dgm

    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x"))
    await layer.run(ctx)
    fake_dgm.snapshot.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.fault_isolation
async def test_l2_e1_dgm_failure_is_contained(core):
    """L2-E1: DGM 抛错时不得让主管道崩溃。"""
    core.settings.enable_evolution = True
    layer = core.get_layer(LayerId.L2)
    fake_dgm = MagicMock()
    fake_dgm.snapshot = AsyncMock(side_effect=RuntimeError("dgm down"))
    core.evolution = fake_dgm

    req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
    ctx = LayerContext(core=core, request=req)
    try:
        result = await layer.run(ctx)
    except RuntimeError:
        pytest.fail("L2 未隔离 DGM 失败，异常泄漏到主管道")
    else:
        assert result.output.get("evolved") is False or "error" in str(result.output).lower()
    finally:
        core.settings.enable_evolution = False


def _install_dgm(core, *, verified: bool = True, with_report: bool = True):
    """Install a deterministic fake DGM engine and return it."""
    dgm = MagicMock()
    dgm.snapshot = AsyncMock(return_value={"modules": ["core"]})
    dgm.propose_variant = AsyncMock(return_value=MagicMock(id="v-1", verified=verified))
    dgm.propose_variant_llm = AsyncMock(return_value=MagicMock(id="v-llm-1", verified=verified))
    if with_report:
        dgm.evaluate_variant = AsyncMock(
            return_value=MagicMock(
                score=0.9,
                pass_rate=0.95,
                benchmark_name="bench",
                reason="" if verified else "verification failed",
            )
        )
    else:
        dgm.evaluate_variant = AsyncMock(return_value=None)
    core.evolution = dgm
    return dgm


@pytest.mark.asyncio
async def test_l2_h1_verified_variant_reported(core):
    """L2-H1: 双门控开启 + 变体通过 → evolved=True、置信度 0.8。"""
    core.settings.enable_evolution = True
    try:
        dgm = _install_dgm(core, verified=True)
        layer = core.get_layer(LayerId.L2)
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        ctx = LayerContext(core=core, request=req)
        result = await layer.run(ctx)

        assert result.output["evolved"] is True
        assert result.output["verified"] is True
        assert result.output["variant_id"] == "v-1"
        assert result.confidence == pytest.approx(0.8)
        assert ctx.scratch["evolution_report"] is not None
        dgm.propose_variant.assert_awaited()
    finally:
        core.settings.enable_evolution = False


@pytest.mark.asyncio
async def test_l2_i2_unverified_variant_quarantined(core):
    """L2-I2: 变体未通过验证 → 隔离 + 记事故，置信度 0.3。"""
    core.settings.enable_evolution = True
    saved = getattr(core, "incident_manager", None)
    incident = MagicMock()
    incident.handle_dgm_variant_rejected = AsyncMock()
    core.incident_manager = incident
    try:
        _install_dgm(core, verified=False)
        layer = core.get_layer(LayerId.L2)
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        result = await layer.run(LayerContext(core=core, request=req))

        assert result.output["verified"] is False
        assert result.output["quarantined"] is True
        assert result.confidence == pytest.approx(0.3)
        incident.handle_dgm_variant_rejected.assert_awaited_once()
    finally:
        core.settings.enable_evolution = False
        core.incident_manager = saved


@pytest.mark.asyncio
async def test_l2_g3_llm_variant_flag_routes_to_llm_path(core):
    """L2-G3: enable_evolution_llm_variants=True → 走 propose_variant_llm。"""
    core.settings.enable_evolution = True
    core.settings.enable_evolution_llm_variants = True
    try:
        dgm = _install_dgm(core, verified=True)
        layer = core.get_layer(LayerId.L2)
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        await layer.run(LayerContext(core=core, request=req))

        dgm.propose_variant_llm.assert_awaited()
        dgm.propose_variant.assert_not_awaited()
    finally:
        core.settings.enable_evolution = False
        core.settings.enable_evolution_llm_variants = False


@pytest.mark.asyncio
@pytest.mark.fault_isolation
async def test_l2_e2_propose_failure_is_contained(core):
    """L2-E2: propose_variant 抛错 → 降级返回，不泄漏异常。"""
    core.settings.enable_evolution = True
    try:
        dgm = _install_dgm(core, verified=True)
        dgm.propose_variant = AsyncMock(side_effect=RuntimeError("propose boom"))
        layer = core.get_layer(LayerId.L2)
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        result = await layer.run(LayerContext(core=core, request=req))

        assert result.output["evolved"] is False
        assert result.output["degraded"] is True
        assert "boom" in str(result.output["error"])
    finally:
        core.settings.enable_evolution = False


# ===========================================================================
# L3 符号层
# ===========================================================================


@pytest.mark.asyncio
async def test_l3_h1_benign_query_passes_governance(core):
    """L3-H1: 普通 query 无违规。"""
    layer = core.get_layer(LayerId.L3)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="写一段说明"))
    result = await layer.run(ctx)
    assert result.output["violations"] == []
    assert ctx.scratch["inference_annotations"] is not None


@pytest.mark.asyncio
async def test_l3_g1_dangerous_query_flagged(core):
    """L3-G1: 危险操作被治理规则识别（违规或拒绝）。"""
    from more_core.core.errors import GovernanceError

    layer = core.get_layer(LayerId.L3)
    req = TaskRequest(type=TaskType.CODE_GENERATION, query="执行 rm -rf / 删除全部文件")
    try:
        result = await layer.run(LayerContext(core=core, request=req))
    except GovernanceError:
        return  # 严格模式下直接拒绝，符合预期
    assert result.output["violations"], "rm -rf 未被治理规则识别"


@pytest.mark.asyncio
async def test_l3_h2_math_reasoning_uses_symbolic_engine(core):
    """L3-H2: 数学任务走 SymPy 并写入 scratch。"""
    layer = core.get_layer(LayerId.L3)
    req = TaskRequest(type=TaskType.MATH_REASONING, query="solve x^2 - 4 = 0")
    ctx = LayerContext(core=core, request=req)
    result = await layer.run(ctx)

    assert "symbolic math" in result.description
    if result.output.get("symbolic_success"):
        assert ctx.scratch.get("symbolic_result") is not None


@pytest.mark.asyncio
async def test_l3_b1_overlong_query_is_flagged(core):
    """L3-B1: 超长 query 触发长度类规则。

    ``strict_ontology`` 默认开启，命中 CRITICAL 级长度规则时 L3 直接抛
    ``GovernanceError``（由编排层转 TaskStatus.REJECTED）。非严格模式下才
    会以 violations 形式返回——两种结果都证明规则生效。
    """
    from more_core.core.errors import GovernanceError

    layer = core.get_layer(LayerId.L3)
    req = TaskRequest(type=TaskType.NLP_TASK, query="请分析：" + "细节" * 3000)
    try:
        result = await layer.run(LayerContext(core=core, request=req))
    except GovernanceError as exc:
        assert "10 000" in str(exc) or "exceeds" in str(exc)
        return
    assert result.output["violations"], "超长 query 应触发长度规则"
    assert result.confidence < 1.0


# ===========================================================================
# L4 认知层
# ===========================================================================


@pytest.mark.asyncio
async def test_l4_h1_writes_difficulty_and_capability(core):
    """L4-H1: 写入 difficulty / capability（0–10 整数）。"""
    layer = core.get_layer(LayerId.L4)
    ctx = LayerContext(
        core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="实现函数")
    )
    await layer.run(ctx)

    for key in ("difficulty", "capability"):
        val = ctx.scratch.get(key)
        assert isinstance(val, int) and 0 <= val <= 10, f"{key}={val!r}"


@pytest.mark.asyncio
async def test_l4_h2_long_query_raises_difficulty(core):
    """L4-H2: 更长/更复杂的 query 难度不低于简单 query。"""
    layer = core.get_layer(LayerId.L4)

    ctx_short = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="hi"))
    await layer.run(ctx_short)

    long_q = "请设计一个分布式系统，包含一致性协议、故障恢复、分片路由与可观测性方案。" * 20
    ctx_long = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query=long_q))
    await layer.run(ctx_long)

    assert ctx_long.scratch["difficulty"] >= ctx_short.scratch["difficulty"]


@pytest.mark.asyncio
async def test_l4_b1_empty_query_still_plans(core):
    """L4-B1: 空 query 不崩溃且仍产出 plan。"""
    layer = core.get_layer(LayerId.L4)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query=""))
    await layer.run(ctx)
    plan = ctx.scratch.get("plan")
    assert isinstance(plan, dict) and "subtasks" in plan


@pytest.mark.asyncio
async def test_l4_i1_plan_available_for_l5_monitoring(core):
    """L4-I1: plan 结构可供 L5 监控。"""
    layer = core.get_layer(LayerId.L4)
    ctx = LayerContext(
        core=core, request=TaskRequest(type=TaskType.CODE_GENERATION, query="写模块")
    )
    await layer.run(ctx)
    plan = ctx.scratch.get("plan") or {}
    assert "difficulty" in plan and "decomposed" in plan


# ===========================================================================
# L5 元认知层
# ===========================================================================


@pytest.mark.asyncio
async def test_l5_h1_calibration_written(core):
    """L5-H1: 正常 actor → 校准结果写入 scratch。"""
    layer = core.get_layer(LayerId.L5)
    req = TaskRequest(type=TaskType.NLP_TASK, query="hello")
    ctx = LayerContext(core=core, request=req, user_id="tester")
    await layer.run(ctx)
    calibration = ctx.scratch.get("calibration")
    assert isinstance(calibration, dict) and "alignment" in calibration


@pytest.mark.asyncio
async def test_l5_g1_blocked_actor_denied(core):
    """L5-G1: 被阻断主体 → ACCESS DENIED 且置信度 0。"""
    layer = core.get_layer(LayerId.L5)
    incident = MagicMock()
    incident.is_actor_blocked = MagicMock(return_value=True)
    incident.handle_unauthorized_access = AsyncMock()
    core.incident_manager = incident

    req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x")
    req.context["actor"] = "blocked-user"
    result = await layer.run(LayerContext(core=core, request=req, user_id="blocked-user"))

    assert result.output.get("blocked") is True
    assert result.confidence == 0.0
    assert "DENIED" in result.description.upper()
    incident.handle_unauthorized_access.assert_awaited()


@pytest.mark.asyncio
async def test_l5_g3_self_mod_gate_off_skips_hyperagent(core):
    """L5-G3: 自修改门控关闭（默认）→ 不得触碰 HyperAgent。"""
    layer = core.get_layer(LayerId.L5)
    saved = core.metacognition.maybe_self_modify
    core.metacognition.maybe_self_modify = AsyncMock()
    try:
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        await layer.run(LayerContext(core=core, request=req))
        core.metacognition.maybe_self_modify.assert_not_awaited()
    finally:
        core.metacognition.maybe_self_modify = saved


@pytest.mark.asyncio
async def test_l5_i1_plan_health_monitored(core):
    """L5-I1: 存在已分解计划时执行计划监控。"""
    layer = core.get_layer(LayerId.L5)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="x"))
    ctx.scratch["plan"] = {"subtasks": ["a", "b"], "decomposed": True, "difficulty": 8}
    await layer.run(ctx)
    assert "plan_health" in ctx.scratch


@pytest.mark.asyncio
async def test_l5_h2_calibration_shape_contract(core):
    """L5-H2: 校准结构含 alignment/confidence/accuracy 且取值合法。"""
    layer = core.get_layer(LayerId.L5)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="hello"))
    result = await layer.run(ctx)

    cal = ctx.scratch["calibration"]
    assert "alignment" in cal
    for key in ("alignment", "confidence", "accuracy"):
        if key in cal:
            assert 0.0 <= float(cal[key]) <= 1.0, f"{key}={cal[key]!r} 越界"
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_l5_g2_blocked_actor_records_incident(core):
    """L5-G2: 被阻断主体访问 → 记录事故（带 layer/actor 权责标记）。"""
    layer = core.get_layer(LayerId.L5)
    saved = getattr(core, "incident_manager", None)
    incident = MagicMock()
    incident.is_actor_blocked = MagicMock(return_value=True)
    incident.handle_unauthorized_access = AsyncMock()
    core.incident_manager = incident
    try:
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x")
        req.context["actor"] = "blocked-user"
        await layer.run(LayerContext(core=core, request=req, user_id="blocked-user"))

        incident.handle_unauthorized_access.assert_awaited_once()
        kwargs = incident.handle_unauthorized_access.await_args.kwargs
        assert kwargs["layer"] == LayerId.L5
        assert kwargs["actor"] == "blocked-user"
    finally:
        core.incident_manager = saved


@pytest.mark.asyncio
async def test_l5_b1_empty_query_still_calibrates(core):
    """L5-B1: 空 query 不崩溃，仍完成校准。"""
    layer = core.get_layer(LayerId.L5)
    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query=""))
    result = await layer.run(ctx)

    assert result.layer == LayerId.L5
    assert "calibration" in ctx.scratch


@pytest.mark.asyncio
async def test_l5_i2_council_review_lowers_optimistic_alignment(core):
    """L5-I2: Council 高风险 + 分歧 → 校准置信度向下修正。"""
    layer = core.get_layer(LayerId.L5)
    council = MagicMock()
    council.synthesis = {"risk_assessment": [{"severity": "high", "title": "risk"}]}
    council.consensus_level = "divided"
    council.errors = []
    council.core_conclusion = "unclear"

    ctx = LayerContext(core=core, request=TaskRequest(type=TaskType.NLP_TASK, query="x"))
    ctx.scratch["plan"] = {"decomposed": True, "subtasks": ["a"], "council_result": council}
    await layer.run(ctx)

    review = ctx.scratch.get("council_review")
    assert review is not None
    assert review["confidence_adjustment"] < 0


@pytest.mark.asyncio
@pytest.mark.fault_isolation
async def test_l5_e1_self_modification_failure_is_contained(core):
    """L5-E1: 自修改（HyperAgent）失败不得击穿主管道。"""
    core.settings.enable_metacognition = True
    saved = core.metacognition.maybe_self_modify
    try:
        core.metacognition.maybe_self_modify = AsyncMock(
            side_effect=RuntimeError("hyperagent down")
        )
        layer = core.get_layer(LayerId.L5)
        req = TaskRequest(type=TaskType.SELF_IMPROVEMENT, query="x", allow_self_improvement=True)
        ctx = LayerContext(core=core, request=req)
        try:
            result = await layer.run(ctx)
        except RuntimeError:
            pytest.fail("L5 未隔离 self-modification 失败，异常泄漏到主管道")
        else:
            assert "calibration" in ctx.scratch
            assert result.layer == LayerId.L5
    finally:
        core.settings.enable_metacognition = False
        core.metacognition.maybe_self_modify = saved


# ===========================================================================
# 跨层集成（Router / Pipeline）
# ===========================================================================


@pytest.mark.parametrize(
    "task_type",
    [
        TaskType.NLP_TASK,
        TaskType.CODE_GENERATION,
        TaskType.MATH_REASONING,
        TaskType.SELF_IMPROVEMENT,
        TaskType.DATA_ANALYSIS,
    ],
)
def test_x_i2_every_task_type_routes_to_registered_layers(core, task_type):
    """X-I2（**迁移到权威来源**）: 各 TaskType 实际管道非空、层均已注册、L0 居末。

    注：`core.router.route()` 会被 Meta-Orchestrator 谱路由覆盖，**不是权威来源**；
    权威决策来自 `core.meta_orchestrator.route()`。
    """
    decision = core.meta_orchestrator.route(task_type, "test")
    assert decision.pipeline, f"{task_type} 权威管道为空"
    for lid in decision.pipeline:
        assert core.get_layer(lid) is not None, f"管道含未注册层 {lid}"
    assert decision.pipeline[-1] == LayerId.L0, "L0 必须在管道末尾"


def test_x_i3_deep_mode_includes_metacognition(core):
    """X-I3（迁移）: 仅 RIVER_DEEP（U≥0.7 或强制监控）才引入 L5 元认知。"""
    normal = core.meta_orchestrator.route(TaskType.SELF_IMPROVEMENT, "自改进")
    deep = core.meta_orchestrator.route(
        TaskType.SELF_IMPROVEMENT, "自改进", require_metacognitive=True
    )
    assert LayerId.L5 not in normal.pipeline
    assert LayerId.L5 in deep.pipeline
    assert deep.pipeline[-1] == LayerId.L0


def test_x_i3b_evolution_layer_reachable_only_in_deep_mode(core):
    """X-I3b（修复后）: L2 进化层仅出现在 RIVER_DEEP，且紧邻 L5 之后。

    修复前三条谱管道均不含 L2，"MORE_ENABLE_EVOLUTION + SELF_IMPROVEMENT→L2"
    契约在生产失效；现 RIVER_DEEP 纳入 L2（其自带双重门控，关闭时 no-op）。
    """
    shallow = core.meta_orchestrator.route(TaskType.SELF_IMPROVEMENT, "自改进")
    deep = core.meta_orchestrator.route(
        TaskType.SELF_IMPROVEMENT, "自改进", require_metacognitive=True
    )
    assert LayerId.L2 not in shallow.pipeline, "轻量路径不应引入 L2"
    assert LayerId.L2 in deep.pipeline, "深度路径必须包含 L2"
    assert deep.pipeline.index(LayerId.L2) == deep.pipeline.index(LayerId.L5) + 1


def test_x_i4_math_l3_inclusion_is_mode_dependent(core):
    """X-I4（迁移）: L3 是否进入数学任务管道由**谱模式**决定，而非任务类型。"""
    short = core.meta_orchestrator.route(TaskType.MATH_REASONING, "解方程")
    complex_q = (
        "请证明并推导一个复杂数学问题：涉及多元微积分、线性代数与概率论的联合求解，"
        "并给出严格证明与误差分析，" * 8
    )
    hard = core.meta_orchestrator.route(TaskType.MATH_REASONING, complex_q)

    assert LayerId.L3 not in short.pipeline, "低不确定度(Village)应跳过 L3"
    assert LayerId.L3 in hard.pipeline, "高不确定度(River)应包含 L3"


@pytest.mark.asyncio
async def test_x_i5_end_to_end_taskresult_is_complete(core):
    """X-I5: 端到端执行产出完整 TaskResult（含阶段耗时）。"""
    result = await core.execute(TaskRequest(type=TaskType.NLP_TASK, query="端到端测试"))
    assert result.task_id
    assert result.status in (TaskStatus.SUCCESS, TaskStatus.FAILED)
    assert result.reasoning_chain, "reasoning_chain 不得为空"
    stages = (result.metadata or {}).get("stage_timings") or {}
    assert stages.get("layers_ms"), "阶段耗时缺失"


@pytest.mark.asyncio
async def test_x_i6_failure_is_diagnosable(core):
    """X-I6: 失败必须可诊断（有原因文本，不静默）。"""
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider(inject_errors=True)
    core.llm._fallback = ["fake"]
    result = await core.execute(TaskRequest(type=TaskType.CODE_GENERATION, query="会失败的任务"))
    if result.status != TaskStatus.SUCCESS:
        assert str(result.output).strip() or (result.metadata or {}).get("escalation")
