"""Tests for L2 — Neural-Evolution Layer (DGM self-improvement, incident response)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from more_core.core.types import LayerId, TaskType
from more_core.layers.base import LayerContext
from more_core.layers.l2_evolution import EvolutionLayer


def _make_ctx(
    enable_evolution: bool = False,
    allow_self_improvement: bool = False,
    enable_evolution_llm_variants: bool = False,
    variant_verified: bool = True,
    has_report: bool = True,
    report_score: float = 0.85,
    report_pass_rate: float = 0.9,
) -> LayerContext:
    core = MagicMock()
    core.incident_manager = None  # fall back to global getter (patched in tests)
    core.settings.enable_evolution = enable_evolution
    core.settings.enable_evolution_llm_variants = enable_evolution_llm_variants

    # DGM engine
    core.evolution = MagicMock()
    core.evolution.snapshot = AsyncMock(return_value={"modules": ["core"]})
    core.evolution.propose_variant = AsyncMock(
        return_value=MagicMock(
            id="variant-001",
            verified=variant_verified,
        )
    )
    core.evolution.propose_variant_llm = AsyncMock(
        return_value=MagicMock(
            id="variant-llm-001",
            verified=variant_verified,
        )
    )
    if has_report:
        core.evolution.evaluate_variant = AsyncMock(
            return_value=MagicMock(
                score=report_score,
                pass_rate=report_pass_rate,
                benchmark_name="default_benchmark",
                reason="verification failed" if not variant_verified else "",
            )
        )
    else:
        core.evolution.evaluate_variant = AsyncMock(return_value=None)

    req = MagicMock()
    req.type = TaskType.SELF_IMPROVEMENT
    req.query = "optimize code generation"
    req.context = {}
    req.id = "test-l2-task"
    req.allow_self_improvement = allow_self_improvement

    ctx = LayerContext(core=core, request=req)
    ctx.scratch = {}
    return ctx


class TestGuardGate:

    @pytest.mark.asyncio
    async def test_evolution_disabled_returns_early(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=False,
                allow_self_improvement=False,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is False
            assert result.confidence == 1.0
            assert "disabled" in result.description
            ctx.core.evolution.snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_when_settings_off(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=False,
                allow_self_improvement=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is False

    @pytest.mark.asyncio
    async def test_disabled_when_request_disallows(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=False,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is False


class TestEvolutionEnabled:

    @pytest.mark.asyncio
    async def test_snapshot_propose_evaluate_cycle(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is True
            ctx.core.evolution.snapshot.assert_called_once()
            ctx.core.evolution.propose_variant.assert_called_once()
            ctx.core.evolution.evaluate_variant.assert_called_once()

    @pytest.mark.asyncio
    async def test_variant_id_in_output(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["variant_id"] == "variant-001"


class TestVariantState:

    @pytest.mark.asyncio
    async def test_verified_variant_high_confidence(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                variant_verified=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["verified"] is True
            assert result.output["quarantined"] is False
            assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_unverified_variant_quarantined(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mgr = MagicMock()
            mgr.handle_dgm_variant_rejected = AsyncMock()
            mock_get_incident.return_value = mgr

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                variant_verified=False,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["verified"] is False
            assert result.output["quarantined"] is True
            assert result.confidence == 0.3
            mgr.handle_dgm_variant_rejected.assert_called_once()


class TestReport:

    @pytest.mark.asyncio
    async def test_report_included_when_present(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                has_report=True,
                report_score=0.85,
                report_pass_rate=0.9,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["score"] == 0.85
            assert result.output["pass_rate"] == 0.9
            assert result.output["benchmark"] == "default_benchmark"
            assert "score=0.850" in result.description

    @pytest.mark.asyncio
    async def test_report_absent_when_none(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                has_report=False,
            )
            result = await EvolutionLayer().process(ctx)
            assert "score" not in result.output
            assert "pass_rate" not in result.output


class TestLLMVariants:

    @pytest.mark.asyncio
    async def test_llm_variant_path_when_enabled(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                enable_evolution_llm_variants=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is True
            ctx.core.evolution.propose_variant_llm.assert_called_once()
            ctx.core.evolution.propose_variant.assert_not_called()

    @pytest.mark.asyncio
    async def test_standard_variant_path_when_llm_disabled(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                enable_evolution_llm_variants=False,
            )
            result = await EvolutionLayer().process(ctx)
            assert result.output["evolved"] is True
            ctx.core.evolution.propose_variant.assert_called_once()
            ctx.core.evolution.propose_variant_llm.assert_not_called()


class TestIncidentResponse:

    @pytest.mark.asyncio
    async def test_unverified_triggers_incident_with_reason(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mgr = MagicMock()
            mgr.handle_dgm_variant_rejected = AsyncMock()
            mock_get_incident.return_value = mgr

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                variant_verified=False,
            )
            await EvolutionLayer().process(ctx)
            mgr.handle_dgm_variant_rejected.assert_called_once_with(
                variant_id="variant-001",
                reason="verification failed",
                verification_output={
                    "score": 0.85,
                    "pass_rate": 0.9,
                },
            )

    @pytest.mark.asyncio
    async def test_unverified_without_report_uses_default_reason(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mgr = MagicMock()
            mgr.handle_dgm_variant_rejected = AsyncMock()
            mock_get_incident.return_value = mgr

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
                variant_verified=False,
                has_report=False,
            )
            await EvolutionLayer().process(ctx)
            mgr.handle_dgm_variant_rejected.assert_called_once_with(
                variant_id="variant-001",
                reason="verification failed",
                verification_output=None,
            )


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_layer_id(self):
        assert EvolutionLayer().layer_id == LayerId.L2

    @pytest.mark.asyncio
    async def test_description_contains_variant_id(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
            )
            result = await EvolutionLayer().process(ctx)
            assert "variant-001" in result.description

    @pytest.mark.asyncio
    async def test_scratch_contains_variant_and_report(self):
        with patch(
            "more_core.layers.l2_evolution.get_incident_manager"
        ) as mock_get_incident:
            mock_get_incident.return_value = MagicMock()

            ctx = _make_ctx(
                enable_evolution=True,
                allow_self_improvement=True,
            )
            await EvolutionLayer().process(ctx)
            assert "evolution_variant" in ctx.scratch
            assert "evolution_report" in ctx.scratch
