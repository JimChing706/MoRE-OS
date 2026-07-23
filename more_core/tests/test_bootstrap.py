"""Tests for bootstrap.py — subsystem factory functions.

Each factory is tested by patching the real module-level constructors so we
can verify the returned dict structure without requiring all 3rd-party deps.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from more_core.core.config import Settings


def _settings(**overrides: object) -> Settings:
    base = dict(
        plugin_dir="tests/plugins",
        log_dir="tests/logs",
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ===================================================================
# init_capabilities
# ===================================================================


class TestInitCapabilities:
    """Patches at the *source* module so lazy imports resolve to mocks."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        with (
            patch("more_core.llm.manager.LLMManager"),
            patch("more_core.llm.dynamic_router.DynamicModelRouter"),
            patch("more_core.llm.state_manager.get_llm_state_manager"),
            patch("more_core.sandbox.secure_sandbox.create_secure_sandbox"),
            patch("more_core.sandbox.secure_sandbox.SandboxConfig"),
            patch("more_core.ontology.engine.OntologyEngine"),
            patch("more_core.metacognition.metacognition.MetacognitionService"),
            patch("more_core.evolution.dgm.DGMEngine"),
            patch("more_core.tools.registry.ToolRegistry"),
            patch("more_core.v3.meta_orchestrator.MetaOrchestrator"),
            patch("more_core.v3.dynamic_guardrails.get_dynamic_guardrails"),
            patch("more_core.memory.store.MemoryStore"),
            patch("more_core.evolution.archive.EvolutionArchive"),
        ):
            yield

    def test_returns_expected_keys(self) -> None:
        from more_core.runtime.bootstrap import init_capabilities

        result = init_capabilities(_settings())
        assert set(result.keys()) == {
            "llm", "task_model_router", "sandbox", "memory",
            "ontology", "metacognition", "evolution_archive",
            "evolution", "tools", "meta_orchestrator",
            "dynamic_guardrails",
        }

    def test_all_values_are_objects(self) -> None:
        from more_core.runtime.bootstrap import init_capabilities

        result = init_capabilities(_settings())
        for key, val in result.items():
            assert val is not None, f"{key} is None"


# ===================================================================
# init_layers
# ===================================================================


class TestInitLayers:
    @pytest.fixture(autouse=True)
    def _patch(self):
        with (
            patch("more_core.router.layer_router.LayerRouter"),
            patch("more_core.layers.l0_execution.ExecutionLayer"),
            patch("more_core.layers.l1_orchestration.OrchestrationLayer"),
            patch("more_core.layers.l2_evolution.EvolutionLayer"),
            patch("more_core.layers.l3_symbolic.SymbolicLayer"),
            patch("more_core.layers.l4_cognition.CognitionLayer"),
            patch("more_core.layers.l5_metacognition.MetacognitionLayer"),
            patch("more_core.governance.audit.AuditLogger"),
            patch("more_core.governance.policy.PolicyEnforcer"),
        ):
            yield

    def test_returns_expected_keys(self) -> None:
        from more_core.runtime.bootstrap import init_layers

        result = init_layers(_settings())
        assert set(result.keys()) == {"router", "layers", "audit", "policy"}

    def test_creates_all_six_layers(self) -> None:
        from more_core.runtime.bootstrap import init_layers
        from more_core.core.types import LayerId

        result = init_layers(_settings())
        expected_ids = {LayerId.L0, LayerId.L1, LayerId.L2,
                        LayerId.L3, LayerId.L4, LayerId.L5}
        assert set(result["layers"].keys()) == expected_ids


# ===================================================================
# init_services
# ===================================================================


class TestInitServices:
    @pytest.fixture(autouse=True)
    def _patch(self):
        _TARGETS = [
            "more_core.channels.manager.ChannelManager",
            "more_core.commands.registry.CommandRegistry",
            "more_core.cron.scheduler.CronScheduler",
            "more_core.deploy.manager.DeploymentManager",
            "more_core.hands.manager.HandManager",
            "more_core.hands.persistence.HandCloner",
            "more_core.hands.persistence.HandPersistence",
            "more_core.hands.registry.HandRegistry",
            "more_core.planning.coordinator.PlanCoordinator",
            "more_core.planning.plan_monitor.PlanMonitor",
            "more_core.planning.token_predictor.TokenPredictor",
            "more_core.planning.workflow_bridge.PlanWorkflowBridge",
            "more_core.plugins.manager.PluginManager",
            "more_core.channels.reconnect.ReconnectManager",
            "more_core.security.output_filter.OutputFilter",
            "more_core.security.rbac.UnifiedRBAC",
            "more_core.security.rbac.set_rbac_instance",
            "more_core.security.taint.TaintTracker",
            "more_core.runtime.sessions.SessionManager",
            "more_core.skills.base.SkillManager",
            "more_core.workflows.engine.WorkflowEngine",
            "more_core.optimization.RateLimiter",
            "more_core.optimization.RequestCache",
            "more_core.optimization.CacheConfig",
            "more_core.optimization.CircuitBreaker",
        ]
        patchers = [patch(t) for t in _TARGETS]
        for p in patchers:
            p.start()
        yield
        for p in patchers:
            p.stop()

    def test_returns_expected_keys(self) -> None:
        from more_core.runtime.bootstrap import init_services

        result = init_services(_settings())
        assert set(result.keys()) == {
            "channels", "cron", "skill_manager",
            "hand_registry", "hands", "commands",
            "plugins", "rbac", "taint_tracker",
            "output_filter", "reconnect_manager",
            "hand_persistence", "hand_cloner",
            "planner", "token_predictor", "workflows",
            "plan_bridge", "plan_monitor",
            "deployment_manager", "session_manager",
            "rate_limiter", "request_cache",
            "llm_circuit_breaker",
        }

    def test_rate_limiter_configured_with_settings(self) -> None:
        from more_core.runtime.bootstrap import init_services
        from more_core.optimization import RateLimiter

        settings = _settings(rate_limit_rps=5.0, rate_limit_burst=10)
        init_services(settings)
        RateLimiter.assert_called_once_with(rate=5.0, burst=10)


# ===================================================================
# _create_memory / _create_evolution_archive
# ===================================================================


class TestCreateMemory:
    def test_default_returns_memory_store(self) -> None:
        from more_core.runtime.bootstrap import _create_memory

        with (
            patch("more_core.memory.store.MemoryStore") as ms,
            patch.dict("os.environ", {"MORE_MEMORY_DB": "", "MORE_EVOLUTION_DB": ""}),
        ):
            result = _create_memory(_settings())
            ms.assert_called_once()
            assert result is not None

    def test_env_var_returns_sqlite_store(self) -> None:
        from more_core.runtime.bootstrap import _create_memory

        with (
            patch("more_core.memory.sqlite_store.SQLiteMemoryStore") as sqlite,
            patch.dict("os.environ", {"MORE_MEMORY_DB": "/tmp/test.db"}),
        ):
            result = _create_memory(_settings())
            sqlite.assert_called_once_with("/tmp/test.db")


class TestCreateEvolutionArchive:
    def test_default_returns_archive(self) -> None:
        from more_core.runtime.bootstrap import _create_evolution_archive

        with (
            patch("more_core.evolution.archive.EvolutionArchive") as ea,
            patch.dict("os.environ", {"MORE_MEMORY_DB": "", "MORE_EVOLUTION_DB": ""}),
        ):
            result = _create_evolution_archive(_settings())
            ea.assert_called_once()
            assert result is not None

    def test_env_var_returns_sqlite_archive(self) -> None:
        from more_core.runtime.bootstrap import _create_evolution_archive

        with (
            patch("more_core.evolution.sqlite_archive.SQLiteEvolutionArchive") as sqla,
            patch.dict("os.environ", {"MORE_EVOLUTION_DB": "/tmp/evo.db"}),
        ):
            result = _create_evolution_archive(_settings())
            sqla.assert_called_once_with("/tmp/evo.db")
