"""L5 — Metacognition Layer (calibration + plan monitoring + HyperAgent).

Responsibilities:
1. **Calibration** — confidence/accuracy alignment (always runs, cheap).
2. **Plan monitoring** — observes active plans, detects anomalies, applies
   adaptive actions (budget reallocation, step skipping, pause/abort).
3. **Self-modification** — HyperAgent (opt-in, gated by settings + request).

Includes incident response for unauthorized modification attempts.
"""

from __future__ import annotations

import logging

from ..core.errors import MoREError
from ..core.types import LayerId
from ..incident_response import get_incident_manager
from ..planning.coordinator import PlanStatus
from .base import Layer, LayerContext, LayerResult

_log = logging.getLogger(__name__)


class MetacognitionLayer(Layer):
    layer_id = LayerId.L5

    async def process(self, ctx: LayerContext) -> LayerResult:
        incident_mgr = get_incident_manager()
        
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

        # --- Self-modification (opt-in) ---
        enable_self_mod = (
            ctx.core.settings.enable_metacognition and ctx.request.allow_self_improvement
        )
        
        if enable_self_mod:
            result = await ctx.core.metacognition.maybe_self_modify(ctx, calibration)
            if result and result.get("modified"):
                _log.info("L5 self-modification applied: %s", result.get("changes", []))

        description = f"calibration aligned={alignment:.2f}"
        if plan_health:
            description += f", plan_health={plan_health.get('status', 'unknown')}"
            # ABORT must interrupt the running pipeline, not just set plan status.
            if plan_health.get("modifications", {}).get("aborted"):
                raise MoREError(
                    f"Plan aborted by L5 metacognition monitor: "
                    f"{plan_health.get('status', 'unknown')}"
                )

        return LayerResult(
            layer=self.layer_id,
            description=description,
            output={"calibration": calibration, "plan_health": plan_health},
            confidence=alignment,
        )

    async def _monitor_plan(self, ctx: LayerContext, confidence: float) -> dict:
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
            s for s in active_plan.steps
            if s.status in (PlanStatus.COMPLETED, PlanStatus.FAILED)
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
