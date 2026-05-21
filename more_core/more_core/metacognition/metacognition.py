"""Facade combining Calibrator + HyperAgent for L5 consumption."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .calibrator import Calibrator
from .hyperagent import HyperAgent

if TYPE_CHECKING:  # pragma: no cover
    from ..layers.base import LayerContext


class MetacognitionService:
    def __init__(self) -> None:
        self.calibrator = Calibrator()
        self.hyperagent = HyperAgent()
        self._governance_callback: Callable[[str, str], bool] | None = None
        self._governance_workflow: Any = None

    def register_governance_callback(self, callback: Callable[[str, str], bool]) -> None:
        self._governance_callback = callback

    def register_governance_workflow(self, workflow: Any) -> None:
        self._governance_workflow = workflow

    async def calibrate(self, ctx: "LayerContext") -> dict[str, object]:
        if ctx.accumulated_steps:
            avg_conf = sum(s.confidence for s in ctx.accumulated_steps) / len(ctx.accumulated_steps)
        else:
            avg_conf = 0.8
        # Derive accuracy from external signals rather than self-referencing
        # confidence.  Use tool success rate when available, governance pass
        # rate, or a neutral prior when no signal exists.
        sbx = ctx.scratch.get("sandbox_result")
        if sbx is not None:
            accuracy = 1.0 if getattr(sbx, "success", False) else 0.0
        elif ctx.scratch.get("code_blocked"):
            accuracy = 0.0
        elif "inference_annotations" in ctx.scratch:
            violations = ctx.scratch.get("violations", [])
            accuracy = 1.0 if not violations else max(0.0, 1.0 - 0.2 * len(violations))
        else:
            accuracy = 0.5  # neutral prior — no external signal available
        self.calibrator.observe(confidence=avg_conf, accuracy=accuracy)
        return self.calibrator.report()

    async def maybe_self_modify(
        self, ctx: "LayerContext", calibration: dict[str, object]
    ) -> None:
        proposal = await self.hyperagent.consider(ctx, calibration)
        if not proposal:
            return

        if self._governance_workflow:
            approval_result = self._governance_workflow.submit_proposal(
                proposal.id,
                {
                    "target": proposal.target,
                    "content": proposal.content,
                    "rationale": proposal.rationale,
                },
            )
            if approval_result == "auto_approved":
                self.hyperagent.approve_proposal(proposal.id, "auto")
            elif approval_result == "manual":
                pass
        elif self._governance_callback:
            approved = self._governance_callback(proposal.id, proposal.rationale)
            if approved:
                self.hyperagent.approve_proposal(proposal.id)
            else:
                self.hyperagent.reject_proposal(proposal.id, "Rejected by governance")

    async def apply_approved_proposals(
        self, dry_run: bool = False
    ) -> list[tuple[str, bool, str]]:
        results = []
        approved = self.hyperagent.list_proposals(status_filter="approved")
        for proposal in approved:
            success, msg = await self.hyperagent.apply_proposal(proposal.id, dry_run)
            results.append((proposal.id, success, msg))
        return results

    def get_calibration_report(self) -> dict[str, Any]:
        return self.calibrator.report()

    def get_proposals(self, status_filter: str | None = None) -> list[Any]:
        return self.hyperagent.list_proposals(status_filter)

    def get_hyperagent(self) -> HyperAgent:
        return self.hyperagent
