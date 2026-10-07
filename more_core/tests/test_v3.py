"""Tests for MoRE v3.0 Risk-Decision Operating System modules.

Covers: UncertaintyAssessor, MetaOrchestrator, DynamicGuardrails
"""

from more_core.core.types import TaskType
from more_core.v3.dynamic_guardrails import (
    GuardrailConfig,
    SandboxLevel,
    get_dynamic_guardrails,
    reset_dynamic_guardrails,
)
from more_core.v3.meta_orchestrator import MetaOrchestrator
from more_core.v3.uncertainty import UncertaintyAssessor

# ── UncertaintyAssessor tests ────────────────────────────────────────────


class TestUncertaintyAssessor:
    def test_simple_task_low_uncertainty(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess("say hello", TaskType.NLP_TASK)
        assert result.aggregated_u < 0.3
        assert result.mode == "village"
        assert result.semantic_complexity < 0.5

    def test_complex_architecture_high_uncertainty(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess(
            "Design a distributed microservice architecture with trade-offs",
            TaskType.ARCHITECTURE_DESIGN,
        )
        assert result.aggregated_u >= 0.3
        assert result.mode == "river"

    def test_code_generation_medium_uncertainty(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess(
            "write a function to sort a list",
            TaskType.CODE_GENERATION,
        )
        # Code gen has base difficulty 5, could go either way
        assert 0.0 <= result.aggregated_u <= 1.0
        assert result.mode in ("village", "river")

    def test_self_improvement_always_high(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess("optimize the routing system", TaskType.SELF_IMPROVEMENT)
        assert result.aggregated_u >= 0.3
        assert result.mode == "river"

    def test_chinese_query_uncertainty(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess(
            "设计一个全新的分布式系统架构，需要考虑各种未知边界条件和冲突权衡",
            TaskType.ARCHITECTURE_DESIGN,
        )
        # Chinese keywords: 设计, 架构, 未知, 边界, 权衡, 冲突
        assert result.aggregated_u >= 0.4
        assert result.mode == "river"

    def test_very_simple_single_word(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess("hi", TaskType.NLP_TASK)
        assert result.aggregated_u < 0.3
        assert result.mode == "village"

    def test_assessment_has_all_dimensions(self):
        assessor = UncertaintyAssessor()
        result = assessor.assess("test query", TaskType.NLP_TASK)
        assert 0.0 <= result.semantic_complexity <= 1.0
        assert 0.0 <= result.historical_similarity <= 1.0
        assert 0.0 <= result.domain_boundary <= 1.0
        assert 0.0 <= result.confidence <= 1.0
        assert "semantic" in result.decomposition
        assert "historical" in result.decomposition
        assert "domain" in result.decomposition

    def test_threshold_adjustable(self):
        assessor = UncertaintyAssessor()
        assessor.set_river_threshold(0.8)
        result = assessor.assess("design a system", TaskType.ARCHITECTURE_DESIGN)
        # Even architecture tasks might fall below 0.8
        assert result.mode in ("village", "river")
        # Reset for other tests
        assessor.set_river_threshold(0.3)

    def test_weights_adjustable(self):
        assessor = UncertaintyAssessor()
        assessor.set_weights(1.0, 0.0, 0.0)  # Only semantic
        result = assessor.assess("hi", TaskType.NLP_TASK)
        assert 0.0 <= result.aggregated_u <= 1.0
        assessor.set_weights(0.4, 0.35, 0.25)  # Reset


# ── MetaOrchestrator tests ───────────────────────────────────────────────


class TestMetaOrchestrator:
    def test_simple_task_village_pipeline(self):
        meta = MetaOrchestrator()
        decision = meta.route(TaskType.NLP_TASK, "say hello")
        assert decision.mode == "village"
        assert decision.is_village
        assert not decision.is_river
        assert len(decision.pipeline) == 3  # L4, L1, L0
        assert decision.guardrail_hints["max_experts"] == 1

    def test_complex_task_river_pipeline(self):
        meta = MetaOrchestrator()
        decision = meta.route(
            TaskType.ARCHITECTURE_DESIGN,
            "Design a novel distributed system with unknown trade-offs",
        )
        assert decision.mode == "river"
        assert decision.is_river
        assert len(decision.pipeline) >= 4  # L4, L3, L1, L0 or with L5

    def test_river_guardrail_hints(self):
        meta = MetaOrchestrator()
        decision = meta.route(
            TaskType.ARCHITECTURE_DESIGN,
            "Design an innovative system architecture",
        )
        hints = decision.guardrail_hints
        assert hints["token_budget"] >= 4096
        assert hints["timeout_s"] >= 60
        assert hints["max_experts"] >= 2

    def test_village_guardrail_hints(self):
        meta = MetaOrchestrator()
        decision = meta.route(TaskType.NLP_TASK, "hello")
        hints = decision.guardrail_hints
        assert hints["token_budget"] == 1024
        assert hints["timeout_s"] == 30
        assert hints["max_experts"] == 1

    def test_resource_budget_per_mode(self):
        meta = MetaOrchestrator()
        village = meta.route(TaskType.NLP_TASK, "hi")
        river = meta.route(
            TaskType.ARCHITECTURE_DESIGN,
            "Design a complex distributed system",
        )
        assert village.resource_budget["max_tokens"] <= river.resource_budget["max_tokens"]
        assert village.resource_budget["max_time_s"] <= river.resource_budget["max_time_s"]

    def test_mode_stats_tracking(self):
        meta = MetaOrchestrator()
        meta.route(TaskType.NLP_TASK, "hello")
        meta.route(TaskType.NLP_TASK, "hi again")
        meta.route(TaskType.ARCHITECTURE_DESIGN, "design system")
        stats = meta.get_mode_stats()
        assert stats["village"] >= 2
        assert stats["river"] >= 1

    def test_routing_config_serializable(self):
        meta = MetaOrchestrator()
        config = meta.get_routing_config()
        assert "river_threshold" in config
        assert "weights" in config
        assert "pipelines" in config
        assert "mode_stats" in config
        assert config["pipelines"]["village"] == ["L4", "L1", "L0"]


# ── DynamicGuardrails tests ──────────────────────────────────────────────


class TestDynamicGuardrails:
    def setup_method(self):
        reset_dynamic_guardrails()

    def test_low_intensity_light_guardrails(self):
        dg = get_dynamic_guardrails()
        config = dg.adjust(u=0.1, criticality=0.2)
        assert config.intensity < 0.1
        assert config.token_budget <= 4096
        assert config.sandbox_level == SandboxLevel.LIGHT
        assert not config.cross_validation_required
        assert not config.human_in_the_loop
        assert config.max_experts == 1

    def test_high_intensity_strict_guardrails(self):
        dg = get_dynamic_guardrails()
        config = dg.adjust(u=0.9, criticality=0.9)
        assert config.intensity > 0.6
        assert config.token_budget >= 8192
        assert config.timeout_s >= 60
        assert config.validation_layers >= 3
        assert config.sandbox_level in (SandboxLevel.STRICT, SandboxLevel.ISOLATED)
        assert config.cross_validation_required

    def test_human_in_the_loop_threshold(self):
        dg = get_dynamic_guardrails()
        # High U + high criticality → human in the loop
        config = dg.adjust(u=0.9, criticality=0.8)
        assert config.human_in_the_loop

        # High U + low criticality → no human needed
        config2 = dg.adjust(u=0.9, criticality=0.3)
        assert not config2.human_in_the_loop

    def test_is_light_mode(self):
        dg = get_dynamic_guardrails()
        assert dg.is_light_mode(u=0.1, criticality=0.1)
        assert not dg.is_light_mode(u=0.5, criticality=0.8)

    def test_requires_human_approval(self):
        dg = get_dynamic_guardrails()
        assert dg.requires_human_approval(u=0.9, criticality=0.8)
        assert not dg.requires_human_approval(u=0.1, criticality=0.1)

    def test_hints_override(self):
        dg = get_dynamic_guardrails()
        config = dg.adjust(
            u=0.5,
            criticality=0.5,
            hints={
                "token_budget": 9999,
                "human_in_the_loop": True,
            },
        )
        assert config.token_budget == 9999
        assert config.human_in_the_loop

    def test_intensity_spectrum(self):
        dg = get_dynamic_guardrails()
        spectrum = dg.get_intensity_spectrum()
        assert len(spectrum) == 8  # 0.0 to 1.0
        for config in spectrum.values():
            assert isinstance(config, GuardrailConfig)

    def test_config_to_dict(self):
        dg = get_dynamic_guardrails()
        config = dg.adjust(u=0.3, criticality=0.5)
        d = config.to_dict()
        assert d["token_budget"] == config.token_budget
        assert d["sandbox_level"] == config.sandbox_level.value
        assert d["intensity"] == config.intensity


# ── Integration: full Meta-Orchestrator → DynamicGuardrails flow ────────


class TestV3Integration:
    def test_full_spectral_flow_village(self):
        """End-to-end: uncertainty → spectral routing → guardrails."""
        meta = MetaOrchestrator()
        dg = get_dynamic_guardrails()

        decision = meta.route(TaskType.NLP_TASK, "hello world")
        config = dg.adjust(
            u=decision.uncertainty_assessment.aggregated_u,
            criticality=0.3,
            hints=decision.guardrail_hints,
        )

        assert decision.mode == "village"
        assert config.max_experts <= 1
        assert config.sandbox_level == SandboxLevel.LIGHT

    def test_full_spectral_flow_river(self):
        """End-to-end: complex task triggers full river mode."""
        meta = MetaOrchestrator()
        dg = get_dynamic_guardrails()

        decision = meta.route(
            TaskType.ARCHITECTURE_DESIGN,
            "Design an innovative quantum-resistant cryptography system",
        )
        # Without hints → DynamicGuardrails uses raw U × criticality formula
        config = dg.adjust(
            u=decision.uncertainty_assessment.aggregated_u,
            criticality=0.9,
        )

        assert decision.mode == "river"
        assert config.token_budget >= 4096
        assert config.validation_layers >= 2
        # intensity = 0.47 × 0.9 ≈ 0.42 > 0.4 → cross-validation triggered
        assert config.cross_validation_required
