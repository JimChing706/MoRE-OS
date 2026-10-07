"""L5 — Metacognition Layer (calibration + plan monitoring + council review + HyperAgent).

Responsibilities:
1. **Calibration** — confidence/accuracy alignment (always runs, cheap).
2. **Council review** — cross-references L4 CouncilResult against calibration;
   detects blind spots where calibration is optimistic but council flagged risks.
3. **Plan monitoring** — observes active plans, detects anomalies, applies
   adaptive actions (budget reallocation, step skipping, pause/abort).
4. **Self-modification** — HyperAgent (opt-in, gated by settings + request).

Includes incident response for unauthorized modification attempts.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.errors import MoREError
from ..core.types import LayerId, TaskType
from ..incident_response import get_incident_manager
from ..planning.coordinator import PlanStatus
from .base import Layer, LayerContext, LayerResult

_log = logging.getLogger(__name__)


class MetacognitionLayer(Layer):
    layer_id = LayerId.L5

    async def process(self, ctx: LayerContext) -> LayerResult:
        incident_mgr = getattr(ctx.core, "incident_manager", None) or get_incident_manager()

        actor = ctx.request.context.get("actor", "anonymous")

        if incident_mgr.is_actor_blocked(actor):
            _log.warning("Blocked actor %s attempted L5 metacognition access", actor)
            await incident_mgr.handle_unauthorized_access(
                layer=self.layer_id,
                actor=actor,
                attempted_action="metacognition_layer_access",
                context={"request_id": ctx.request.id},
            )
            return LayerResult(
                layer=self.layer_id,
                description="ACCESS DENIED - actor blocked",
                output={"error": "unauthorized", "blocked": True},
                confidence=0.0,
            )

        # --- Calibration (always runs) ---
        calibration = await ctx.core.metacognition.calibrate(ctx)
        ctx.scratch["calibration"] = calibration
        alignment = float(calibration["alignment"])

        # --- Plan monitoring (if active plan exists) ---
        plan_health = None
        plan = ctx.scratch.get("plan")
        if plan and plan.get("decomposed"):
            plan_health = await self._monitor_plan(ctx, alignment)
            ctx.scratch["plan_health"] = plan_health

        # --- Council review (cross-reference L4 CouncilResult with calibration) ---
        council_review = None
        plan_data = ctx.scratch.get("plan", {})
        council_result = plan_data.get("council_result")
        if council_result:
            _alignment_before = alignment
            council_review = self._review_council_output(
                council_result,
                calibration,
                alignment,
            )
            ctx.scratch["council_review"] = council_review
            if council_review.get("confidence_adjustment", 0.0) < 0:
                alignment = max(0.0, alignment + council_review["confidence_adjustment"])
                _log.info(
                    "L5 council review adjusted alignment: %.2f → %.2f (reason: %s)",
                    _alignment_before,
                    alignment,
                    council_review.get("adjustment_reason", ""),
                )
            if council_review.get("risks", []):
                _log.info(
                    "L5 council review flagged %d risks for task %s",
                    council_review.get("risk_count", len(council_review["risks"])),
                    ctx.request.id,
                )
            self._record_council_review(ctx, council_review, _alignment_before, alignment)

        # --- Self-modification (opt-in) ---
        enable_self_mod = (
            ctx.core.settings.enable_metacognition and ctx.request.allow_self_improvement
        )

        self_mod_error: str | None = None
        if enable_self_mod:
            # HyperAgent self-modification is opt-in and non-critical: a failure
            # in the proposal/governance path must be contained so it can never
            # crash the host task pipeline (mirrors L2's DGM containment).
            try:
                result = await ctx.core.metacognition.maybe_self_modify(ctx, calibration)
                if result and result.get("modified"):
                    _log.info("L5 self-modification applied: %s", result.get("changes", []))
            except Exception as exc:  # noqa: BLE001 - containment is the contract
                self_mod_error = str(exc)
                _log.error("L5 self-modification failed (contained): %s", exc, exc_info=True)
                ctx.scratch["self_modification_error"] = self_mod_error

        description = f"calibration aligned={alignment:.2f}"
        if council_review:
            adj = council_review.get("confidence_adjustment", 0.0)
            description += f", council_adj={adj:+.2f}"
        if plan_health:
            description += f", plan_health={plan_health.get('status', 'unknown')}"
            # ABORT must interrupt the running pipeline, not just set plan status.
            # Exception: code generation tasks should NOT be aborted mid-stream;
            # the generated code is already partially complete and may still be
            # useful even if the plan budget is exceeded.
            is_code = ctx.request.type in (
                TaskType.CODE_GENERATION,
                TaskType.CODE_DEBUGGING,
                TaskType.CODE_TESTING,
                TaskType.CODE_REVIEW,
            )
            if plan_health.get("modifications", {}).get("aborted") and not is_code:
                raise MoREError(
                    f"Plan aborted by L5 metacognition monitor: "
                    f"{plan_health.get('status', 'unknown')}"
                )
            elif plan_health.get("modifications", {}).get("aborted"):
                _log.warning(
                    "Plan abort suppressed for code task %s (budget exceeded but code preserved)",
                    ctx.request.id,
                )

        if self_mod_error:
            description += f", self_mod_degraded={self_mod_error}"

        return LayerResult(
            layer=self.layer_id,
            description=description,
            output={
                "calibration": calibration,
                "plan_health": plan_health,
                "council_review": council_review,
                "structured_plan": ctx.scratch.get("structured_plan"),
                "self_modification_error": self_mod_error,
            },
            confidence=alignment,
        )

    def _record_council_review(
        self,
        ctx: LayerContext,
        review: dict[str, Any],
        before: float,
        after: float,
    ) -> None:
        """Emit one council-review telemetry row. Never raises."""
        try:
            from ..governance import observability as _obs

            risks = review.get("risks") or []
            _obs.record_council_review(
                request_id=ctx.request.id,
                consensus=str(review.get("consensus_level", "")),
                risk_count=int(review.get("risk_count", len(risks)) or 0),
                high_risks=int(review.get("high_risk_count", 0) or 0),
                errors=int(review.get("council_errors", 0) or 0),
                alignment_before=float(before),
                adjustment=float(review.get("confidence_adjustment", 0.0) or 0.0),
                alignment_after=float(after),
            )
        except Exception:  # pragma: no cover - telemetry must never break L5  # noqa: BLE001, S110
            pass

    async def _monitor_plan(self, ctx: LayerContext, confidence: float) -> dict[str, Any]:
        """Monitor active plan execution and apply adaptive interventions.

        Returns a health summary dict for downstream consumption.
        """
        monitor = ctx.core.plan_monitor
        planner = ctx.core.planner

        # Find the active plan for this request (if any)
        plan_data = ctx.scratch.get("plan", {})
        plan_id = plan_data.get("plan_id")
        active_plan = planner.get_plan(plan_id) if plan_id else None

        if active_plan is None:
            # No tracked plan — just report observation
            return {"status": "no_active_plan", "confidence": confidence}

        # Find the most recently completed step
        completed_steps = [
            s for s in active_plan.steps if s.status in (PlanStatus.COMPLETED, PlanStatus.FAILED)
        ]
        if not completed_steps:
            return {"status": "plan_pending", "plan_id": active_plan.id}

        latest_step = completed_steps[-1]

        # Observe and get recommended actions
        actions = monitor.observe_step_completion(active_plan, latest_step, confidence)

        # Apply adaptive actions if any
        modifications = {}
        if actions:
            modifications = monitor.apply_adaptive_actions(active_plan, actions)
            _log.info(
                "Plan %s: L5 adaptive actions applied: %s",
                active_plan.id,
                [a.value for a in actions],
            )

        # Generate health report
        report = monitor.get_health_report(active_plan)
        return {
            "status": report.status,
            "plan_id": report.plan_id,
            "progress_pct": report.progress_pct,
            "burn_rate": report.budget_burn_rate,
            "will_exceed_budget": report.budget_will_exceed,
            "confidence_trend": report.confidence_trend,
            "actions_taken": [a.value for a in actions],
            "modifications": modifications,
        }

    @staticmethod
    def _review_council_output(
        council_result: Any,
        calibration: dict[str, Any],
        current_alignment: float,
    ) -> dict[str, Any]:
        """Cross-reference L4's CouncilResult against L5 calibration.

        Detects blind spots where the multi-perspective council flagged
        risks that calibration alone might have missed.
        """
        synthesis = getattr(council_result, "synthesis", None) or {}
        risks = synthesis.get("risk_assessment", []) if isinstance(synthesis, dict) else []
        consensus_level = getattr(council_result, "consensus_level", "unknown")
        errors = getattr(council_result, "errors", [])
        core_conclusion = getattr(council_result, "core_conclusion", "")

        risk_count = len(risks)
        high_risks = sum(1 for r in risks if isinstance(r, dict) and r.get("severity") == "high")
        divided = consensus_level == "divided"
        weak_consensus = consensus_level in ("weak", "divided")

        adjustment = 0.0
        reasons = []

        if divided:
            adjustment -= 0.15
            reasons.append("council consensus is divided")
        elif weak_consensus:
            adjustment -= 0.08
            reasons.append(f"council consensus is {consensus_level}")

        if high_risks > 0:
            penalty = -0.05 * min(high_risks, 3)
            adjustment += penalty
            reasons.append(f"{high_risks} high-severity risk(s) flagged")

        if risk_count >= 3 and current_alignment > 0.85:
            adjustment -= 0.05
            reasons.append("high risk count despite optimistic calibration")

        if errors:
            adjustment -= 0.05 * min(len(errors), 3)
            reasons.append(f"{len(errors)} council error(s)")

        adjustment = round(max(adjustment, -0.5), 3)

        return {
            "confidence_adjustment": adjustment,
            "adjustment_reason": "; ".join(reasons) if reasons else "no adjustment needed",
            "risks": risks[:5],
            "risk_count": risk_count,
            "high_risk_count": high_risks,
            "consensus_level": consensus_level,
            "core_conclusion": (core_conclusion[:200] if core_conclusion else ""),
            "council_errors": len(errors),
        }
