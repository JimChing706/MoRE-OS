"""L2 — Neural-Evolution Layer (DGM-style self-improvement, *opt-in*).

Full cycle: snapshot → propose → **evaluate** → verify/reject → archive.
The evaluation uses :class:`BenchmarkRunner` if wired into the DGM engine.
Only runs when both ``Settings.enable_evolution`` AND
``TaskRequest.allow_self_improvement`` are true.
Includes incident response for unverified variants.
"""

from __future__ import annotations

import logging

from ..core.types import LayerId
from ..incident_response import get_incident_manager
from .base import Layer, LayerContext, LayerResult

_log = logging.getLogger(__name__)


class EvolutionLayer(Layer):
    layer_id = LayerId.L2

    async def process(self, ctx: LayerContext) -> LayerResult:
        enabled = ctx.core.settings.enable_evolution and ctx.request.allow_self_improvement
        if not enabled:
            return LayerResult(
                layer=self.layer_id,
                description="evolution disabled (governance gate)",
                output={"evolved": False},
                confidence=1.0,
            )

        incident_mgr = getattr(ctx.core, "incident_manager", None) or get_incident_manager()

        dgm = ctx.core.evolution
        snapshot = await dgm.snapshot()
        if ctx.core.settings.enable_evolution_llm_variants:
            variant = await dgm.propose_variant_llm(snapshot, ctx.request)
        else:
            variant = await dgm.propose_variant(snapshot, ctx.request)
        ctx.scratch["evolution_variant"] = variant

        report = await dgm.evaluate_variant(variant)
        ctx.scratch["evolution_report"] = report

        if not variant.verified:
            await incident_mgr.handle_dgm_variant_rejected(
                variant_id=variant.id,
                reason=report.reason if report else "verification failed",
                verification_output={"score": report.score, "pass_rate": report.pass_rate}
                if report
                else None,
            )
            _log.error(
                "L2 SECURITY INCIDENT: Unverified variant %s quarantined",
                variant.id,
            )

        out = {
            "evolved": True,
            "variant_id": variant.id,
            "verified": variant.verified,
            "quarantined": not variant.verified,
        }
        if report is not None:
            out.update(
                {
                    "score": report.score,
                    "pass_rate": report.pass_rate,
                    "benchmark": report.benchmark_name,
                }
            )
            _log.info(
                "L2 evolution: variant=%s verified=%s score=%.3f",
                variant.id,
                variant.verified,
                report.score,
            )

        return LayerResult(
            layer=self.layer_id,
            description=(
                f"variant {variant.id} — "
                + ("verified" if variant.verified else "UNVERIFIED/QUARANTINED")
                + (f" (score={report.score:.3f})" if report else "")
            ),
            output=out,
            confidence=0.8 if variant.verified else 0.3,
        )
