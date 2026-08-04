"""Tests for MoRECore orchestrator — composition root + task execution pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.core.config import Settings
from more_core.core.deliverable import DeliverableKind
from more_core.core.errors import GovernanceError, MoREError
from more_core.core.types import (
    LayerId,
    TaskRequest,
    TaskStatus,
)
from more_core.layers.base import Layer, LayerContext, LayerResult
from more_core.router.layer_router import RoutingDecision
from more_core.runtime.orchestrator import MoRECore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_core(**attrs: object) -> "MoRECore":
    """Create a MoRECore with all three bootstrap factories mocked.

    Additional keyword arguments are set as attributes on the finished
    instance so callers can inject pre-configured mocks easily.
    """
    from more_core.runtime.orchestrator import MoRECore

    settings = Settings(
        plugin_dir="tests/plugins",
        log_dir="tests/logs",
        providers=[],
        fallback_chain=[],
    )
    with (
        patch("more_core.runtime.orchestrator.init_capabilities") as mc,
        patch("more_core.runtime.orchestrator.init_layers") as ml,
        patch("more_core.runtime.orchestrator.init_services") as ms,
    ):
        mc.return_value = {
            "llm": MagicMock(),
            "task_model_router": MagicMock(),
            "sandbox": MagicMock(),
            "memory": MagicMock(),
            "ontology": MagicMock(),
            "metacognition": MagicMock(),
            "evolution_archive": MagicMock(),
            "evolution": MagicMock(),
            "tools": MagicMock(),
            "meta_orchestrator": None,
            "dynamic_guardrails": None,
        }
        ml.return_value = {
            "router": MagicMock(),
            "layers": {},
            "audit": MagicMock(),
            "policy": MagicMock(),
        }
        ms.return_value = {
            "channels": MagicMock(),
            "cron": MagicMock(),
            "skill_manager": MagicMock(),
            "hand_registry": MagicMock(),
            "hands": MagicMock(),
            "commands": MagicMock(),
            "plugins": MagicMock(),
            "rbac": MagicMock(),
            "taint_tracker": MagicMock(),
            "output_filter": MagicMock(),
            "reconnect_manager": MagicMock(),
            "hand_persistence": MagicMock(),
            "hand_cloner": MagicMock(),
            "planner": MagicMock(),
            "token_predictor": MagicMock(),
            "workflows": MagicMock(),
            "plan_bridge": MagicMock(),
            "plan_monitor": MagicMock(),
            "deployment_manager": MagicMock(),
            "session_manager": MagicMock(),
            "rate_limiter": MagicMock(),
            "request_cache": MagicMock(),
            "llm_circuit_breaker": MagicMock(),
        }
        core = MoRECore(settings)
    for k, v in attrs.items():
        setattr(core, k, v)
    return core


def _mock_layer(layer_id: LayerId, output: str = "ok") -> MagicMock:
    m = MagicMock(spec=Layer)
    m.layer_id = layer_id
    m.run = AsyncMock(
        return_value=LayerResult(
            layer=layer_id, description=f"{layer_id.value} done", output=output,
        ),
    )
    return m


def _execute_core() -> "MoRECore":
    """Return a pre-configured core for execute()-path tests."""
    core = _make_core()

    core._rate_limiter.acquire = AsyncMock(return_value=True)
    core._request_cache.get = AsyncMock(return_value=None)
    core._request_cache.set = AsyncMock()
    core.router.route = MagicMock(
        return_value=RoutingDecision(pipeline=[LayerId.L0], reasoning="direct"),
    )
    core.llm.list_providers = MagicMock(return_value=["fake"])
    core.event_bus.publish = AsyncMock()
    core.audit.log = MagicMock()
    core.policy.check = MagicMock()
    core._metrics.record_request = MagicMock()
    core.output_filter.filter = MagicMock(side_effect=lambda x: x)

    taint_scope = MagicMock()
    taint_scope.track = MagicMock()
    taint_scope.sanitize = MagicMock()
    taint_scope.check = MagicMock(return_value=True)
    taint_scope.cleanup = MagicMock()
    core.taint_tracker.scope = MagicMock(return_value=taint_scope)

    core.layers = {LayerId.L0: _mock_layer(LayerId.L0, output="hello from L0")}
    return core


# ===================================================================
# Construction
# ===================================================================


def test_init_with_minimal_settings() -> None:
    core = _make_core()
    assert isinstance(core.settings, Settings)
    assert hasattr(core, "llm")
    assert hasattr(core, "router")
    assert hasattr(core, "layers")
    assert hasattr(core, "event_bus")
    assert hasattr(core, "_rate_limiter")
    assert hasattr(core, "_request_cache")
    assert hasattr(core, "_llm_circuit_breaker")


def test_core_registers_subsystems() -> None:
    core = _make_core()
    stats = core.registry.stats()
    assert stats["total_services"] > 0
    for name in ("llm", "router", "memory", "cron", "skills", "security"):
        assert core.registry.get(name) is not None, name


def test_from_env_delegation() -> None:
    with (
        patch("more_core.runtime.orchestrator.MoRECore.__init__", return_value=None) as mock_init,
        patch("more_core.core.config.Settings.from_env") as mock_env,
    ):
        from more_core.runtime.orchestrator import MoRECore

        result = MoRECore.from_env()
        mock_env.assert_called_once()
        mock_init.assert_called_once_with(mock_env.return_value)
        assert result is not None


# ===================================================================
# Layer lifecycle
# ===================================================================


class TestLayerLifecycle:
    def test_replace_and_get(self) -> None:
        core = _make_core()
        core.layers = {}
        l0 = _mock_layer(LayerId.L0)
        core.replace_layer(l0)
        assert core.get_layer(LayerId.L0) is l0

    def test_get_missing_raises_key_error(self) -> None:
        core = _make_core()
        core.layers = {}
        with pytest.raises(KeyError):
            core.get_layer(LayerId.L5)


# ===================================================================
# Stats
# ===================================================================


class TestStats:
    def test_cache_stats(self) -> None:
        core = _make_core()
        core._request_cache.stats = MagicMock(return_value={"hits": 5, "misses": 2})
        assert core.get_cache_stats() == {"hits": 5, "misses": 2}

    def test_rate_limiter_stats(self) -> None:
        core = _make_core()
        core._rate_limiter._burst = 42
        stats = core.get_rate_limiter_stats()
        assert stats["rate_limiter"] == "token_bucket"
        assert stats["config"]["burst"] == 42


# ===================================================================
# Task expectation resolution  (pure logic, no mocking needed)
# ===================================================================


class TestResolveExpectation:
    def test_explicit_expectation(self) -> None:
        core = _make_core()
        req = TaskRequest(
            query="build a widget",
            expectation={
                "contract": {
                    "kind": "code",
                    "required_dimensions": ["core_output", "tests"],
                },
                "kill_criteria": [{"condition": "no_output"}],
                "target_confidence": 90.0,
            },
        )
        exp = core._resolve_expectation(req)
        assert exp.contract.kind == DeliverableKind.CODE
        assert "core_output" in exp.contract.required_dimensions
        assert exp.target_confidence == 90.0
        assert len(exp.kill_criteria) == 1

    def test_deliverable_kind_default(self) -> None:
        core = _make_core()
        req = TaskRequest(query="analyze", deliverable_kind="analysis")
        exp = core._resolve_expectation(req)
        assert exp.contract.kind == DeliverableKind.ANALYSIS

    def test_fallback_to_empty_expectation(self) -> None:
        core = _make_core()
        req = TaskRequest(query="hello")
        exp = core._resolve_expectation(req)
        assert exp.contract.kind == DeliverableKind.CUSTOM
        assert exp.contract.required_dimensions == []

    def test_unknown_kind_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        core = _make_core()
        req = TaskRequest(query="x", deliverable_kind="bogus")
        exp = core._resolve_expectation(req)
        assert exp.contract.kind == DeliverableKind.CUSTOM
        assert "bogus" in caplog.text


# ===================================================================
# Pipeline execution (_run_pipeline)
# ===================================================================


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_executes_layers_in_order(self) -> None:
        core = _make_core()
        l1 = _mock_layer(LayerId.L1, output="step1")
        l0 = _mock_layer(LayerId.L0, output="final")
        core.layers = {LayerId.L1: l1, LayerId.L0: l0}
        core.event_bus.publish = AsyncMock()
        core.audit = MagicMock()

        decision = RoutingDecision(pipeline=[LayerId.L1, LayerId.L0], reasoning="")
        ctx = LayerContext(core=MagicMock(), request=TaskRequest(query="t"))

        await core._run_pipeline(decision, ctx)

        l1.run.assert_awaited_once()
        l0.run.assert_awaited_once()
        assert ctx.scratch.get("_l0_output") == "final"

    @pytest.mark.asyncio
    async def test_convergence_terminates_early(self) -> None:
        core = _make_core()
        l1 = _mock_layer(LayerId.L1, output="good enough")
        l0 = _mock_layer(LayerId.L0, output="extra")
        core.layers = {LayerId.L1: l1, LayerId.L0: l0}
        core.event_bus.publish = AsyncMock()
        core.audit = MagicMock()

        decision = RoutingDecision(pipeline=[LayerId.L1, LayerId.L0], reasoning="")

        tracker = MagicMock()
        tracker.record.return_value.should_terminate = True

        ctx = LayerContext(core=MagicMock(), request=TaskRequest(query="t"))
        await core._run_pipeline(decision, ctx, convergence_tracker=tracker)

        l0.run.assert_not_called()
        assert ctx.scratch.get("_convergence_terminated") is True

    @pytest.mark.asyncio
    async def test_captures_l0_in_scratch(self) -> None:
        core = _make_core()
        l0 = _mock_layer(LayerId.L0, output="only-layer output")
        core.layers = {LayerId.L0: l0}
        core.event_bus.publish = AsyncMock()
        core.audit = MagicMock()

        decision = RoutingDecision(pipeline=[LayerId.L0], reasoning="")
        ctx = LayerContext(core=MagicMock(), request=TaskRequest(query="t"))
        await core._run_pipeline(decision, ctx)
        assert ctx.scratch.get("_l0_output") == "only-layer output"


# ===================================================================
# execute()  —  full task execution
# ===================================================================


class TestExecute:
    @pytest.fixture
    def core(self) -> "MoRECore":
        return _execute_core()

    @pytest.mark.asyncio
    async def test_happy_path(self, core: "MoRECore") -> None:
        result = await core.execute(TaskRequest(query="hello"))
        assert result.status == TaskStatus.SUCCESS
        assert "hello from L0" in result.output
        assert result.task_id is not None

    @pytest.mark.asyncio
    async def test_rate_limit_rejects_request(self, core: "MoRECore") -> None:
        core._rate_limiter.acquire = AsyncMock(return_value=False)
        result = await core.execute(TaskRequest(query="x"))
        assert result.status == TaskStatus.REJECTED
        assert "rate limit" in result.output

    @pytest.mark.asyncio
    async def test_cached_response_returned_directly(self, core: "MoRECore") -> None:
        core._request_cache.get = AsyncMock(return_value="cached-output")
        result = await core.execute(TaskRequest(query="repeated"))
        assert result.status == TaskStatus.SUCCESS
        assert result.output == "cached-output"

    @pytest.mark.asyncio
    async def test_governance_error_rejected(self, core: "MoRECore") -> None:
        core.policy.check = MagicMock(side_effect=GovernanceError("blocked by policy"))
        result = await core.execute(TaskRequest(query="sensitive"))
        assert result.status == TaskStatus.REJECTED
        assert "blocked by policy" in result.output

    @pytest.mark.asyncio
    async def test_more_error_grants_failed(self, core: "MoRECore") -> None:
        core.layers[LayerId.L0].run = AsyncMock(side_effect=MoREError("layer blew up"))
        result = await core.execute(TaskRequest(query="boom"))
        assert result.status == TaskStatus.FAILED
        assert "layer blew up" in result.output

    @pytest.mark.asyncio
    async def test_unexpected_exception_caught(self, core: "MoRECore") -> None:
        core.layers[LayerId.L0].run = AsyncMock(side_effect=ValueError("weird"))
        result = await core.execute(TaskRequest(query="weird"))
        assert result.status == TaskStatus.FAILED
        assert "internal error" in result.output

    @pytest.mark.asyncio
    async def test_timeout_results_in_failed(self, core: "MoRECore") -> None:
        async def _slow(_ctx: LayerContext) -> LayerResult:
            await asyncio.sleep(100)
            return LayerResult(layer=LayerId.L0, description="slow", output="x")

        core.layers[LayerId.L0].run = AsyncMock(side_effect=_slow)
        req = TaskRequest(query="slow", timeout_s=0.01)
        result = await core.execute(req)
        assert result.status == TaskStatus.FAILED
        assert "timed out" in result.output

    @pytest.mark.asyncio
    async def test_zen_19_violation_rejects(self, core: "MoRECore") -> None:
        zen = MagicMock()
        zen.check_violation.side_effect = (
            lambda rule_id, ctx: rule_id == "ZEN-19"
        )
        with patch("more_core.runtime.orchestrator.get_enforcer", return_value=zen):
            result = await core.execute(TaskRequest(query="rm -rf /"))
        assert result.status == TaskStatus.REJECTED
        assert "forbidden" in result.output.lower() or "ZEN-19" in result.output

    @pytest.mark.asyncio
    async def test_post_processing_crash_returns_failed(self, core: "MoRECore") -> None:
        core.output_filter.filter = MagicMock(side_effect=RuntimeError("filter boom"))
        result = await core.execute(TaskRequest(query="boom"))
        assert result.status == TaskStatus.FAILED
        assert "filter boom" in result.output

    @pytest.mark.asyncio
    async def test_post_processing_crash_clears_request_context(self, core: "MoRECore") -> None:
        import more_core.runtime.orchestrator as orch

        core.output_filter.filter = MagicMock(side_effect=RuntimeError("boom"))
        clear_spy = MagicMock(wraps=orch.clear_context)
        with patch.object(orch, "clear_context", clear_spy):
            result = await core.execute(TaskRequest(query="boom"))
        assert result.status == TaskStatus.FAILED
        clear_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_meta_orchestrator_overrides_pipeline(self, core: "MoRECore") -> None:
        meta = MagicMock()
        meta.route.return_value = MagicMock(
            pipeline=[LayerId.L5, LayerId.L0],
            reasoning="spectral override",
            uncertainty_assessment=MagicMock(aggregated_u=0.3),
            guardrail_hints={},
            mode="village",
        )
        dg = MagicMock()
        dg.adjust.return_value = MagicMock(
            to_dict=lambda: {"budget": 0.5},
            reasoning="adjusted guardrails",
        )

        core.meta_orchestrator = meta
        core.dynamic_guardrails = dg
        core.layers[LayerId.L5] = _mock_layer(LayerId.L5, output="meta done")

        result = await core.execute(TaskRequest(query="meta test"))
        assert result.status == TaskStatus.SUCCESS
        meta.route.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_filter_applied(self, core: "MoRECore") -> None:
        core.output_filter.filter = MagicMock(return_value="filtered-output")
        core.layers = {
            LayerId.L0: _mock_layer(LayerId.L0, output="raw output"),
        }
        result = await core.execute(TaskRequest(query="filter me"))
        assert result.output == "filtered-output"

    @pytest.mark.asyncio
    async def test_partial_status_when_critical_dimension_missing(
        self, core: "MoRECore",
    ) -> None:
        result = await core.execute(TaskRequest(query="hello"))
        assert result.status == TaskStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_performance_metrics_populated(self, core: "MoRECore") -> None:
        result = await core.execute(TaskRequest(query="perf test"))
        assert result.performance.total_duration_ms >= 0
        assert result.performance.tokens_used == 0
        assert result.performance.layer_transitions >= 0

    @pytest.mark.asyncio
    async def test_taint_violation_logged(self, core: "MoRECore", caplog: pytest.LogCaptureFixture) -> None:
        taint_scope = MagicMock()
        taint_scope.track = MagicMock()
        taint_scope.sanitize = MagicMock()
        taint_scope.check = MagicMock(return_value=False)
        taint_scope.cleanup = MagicMock()
        core.taint_tracker.scope = MagicMock(return_value=taint_scope)

        await core.execute(TaskRequest(query="tainted"))
        assert "taint violation" in caplog.text

    @pytest.mark.asyncio
    async def test_successful_result_cached(self, core: "MoRECore") -> None:
        core._request_cache.set = AsyncMock()
        await core.execute(TaskRequest(query="cache me"))
        core._request_cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_result_not_cached(self, core: "MoRECore") -> None:
        core._request_cache.set = AsyncMock()
        core.policy.check = MagicMock(side_effect=GovernanceError("nope"))
        await core.execute(TaskRequest(query="no cache"))
        core._request_cache.set.assert_not_called()


# ===================================================================
# stream_execute()
# ===================================================================


class TestStreamExecute:
    @pytest.mark.asyncio
    async def test_streams_tokens(self) -> None:
        core = _make_core()
        core._rate_limiter.acquire = AsyncMock(return_value=True)
        core.router.route = MagicMock(
            return_value=RoutingDecision(pipeline=[LayerId.L0], reasoning="direct"),
        )
        core.llm.list_providers = MagicMock(return_value=["fake"])
        core.policy.check = MagicMock()

        taint_scope = MagicMock()
        taint_scope.track = MagicMock()
        taint_scope.sanitize = MagicMock()
        taint_scope.check = MagicMock(return_value=True)
        taint_scope.cleanup = MagicMock()
        core.taint_tracker.scope = MagicMock(return_value=taint_scope)

        core.output_filter.filter = MagicMock(side_effect=lambda x: x)

        async def _fake_stream(_req: object) -> "AsyncIterator[str]":
            yield "hello"
            yield " world"

        core.llm.stream = _fake_stream

        chunks = [c async for c in core.stream_execute(TaskRequest(query="test"))]
        assert any("hello" in c for c in chunks), chunks
        assert any('"event": "done"' in c for c in chunks)

    @pytest.mark.asyncio
    async def test_stream_rate_limited(self) -> None:
        core = _make_core()
        core._rate_limiter.acquire = AsyncMock(return_value=False)

        chunks = [c async for c in core.stream_execute(TaskRequest(query="x"))]
        assert any("rate limit" in c for c in chunks)


# ===================================================================
# Lazy properties  (MCP / A2A)
# ===================================================================


class TestLazyProperties:
    def test_mcp_server_lazy_init(self) -> None:
        core = _make_core()
        core.tools.list_tools = MagicMock(return_value=[])
        srv = core.mcp_server
        assert srv is core.mcp_server

    def test_mcp_client_lazy_init(self) -> None:
        core = _make_core()
        client = core.mcp_client
        assert client is core.mcp_client

    def test_a2a_server_lazy_init(self) -> None:
        core = _make_core()
        srv = core.a2a_server
        assert srv is core.a2a_server


# ===================================================================
# llm_generate_safe — circuit breaker wrapper
# ===================================================================


class TestLLMGenerateSafe:
    @pytest.mark.asyncio
    async def test_forwards_to_circuit_breaker(self) -> None:
        core = _make_core()
        core._llm_circuit_breaker.call = AsyncMock(return_value="result")
        req = MagicMock()
        result = await core.llm_generate_safe(req)
        core._llm_circuit_breaker.call.assert_awaited_once_with(core.llm.generate, req)
        assert result == "result"
