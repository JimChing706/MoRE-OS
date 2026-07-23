"""Pre-execution policy enforcement."""

from __future__ import annotations

from ..core.config import Settings
from ..core.errors import GovernanceError
from ..core.types import TaskRequest
from typing import Any


class PolicyEnforcer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(self, request: TaskRequest) -> None:
        if request.allow_self_improvement and not self._settings.enable_metacognition:
            raise GovernanceError(
                "allow_self_improvement=True but Settings.enable_metacognition is disabled"
            )
        if request.timeout_s <= 0 or request.timeout_s > 600:
            raise GovernanceError(f"invalid timeout_s={request.timeout_s}")


class GovernanceWorkflow:
    APPROVAL_REQUIRED = "approval_required"
    AUTO_APPROVED = "auto_approved"
    MANUAL_ONLY = "manual_only"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._approvers: dict[str, str] = {}
        self._pending_approvals: dict[str, dict[str, Any]] = {}

    def register_approver(self, approver_id: str, approver_type: str = "human") -> None:
        self._approvers[approver_id] = approver_type

    def submit_proposal(self, proposal_id: str, proposal_data: dict[str, Any]) -> str:
        approval_mode = self._determine_approval_mode(proposal_data)
        self._pending_approvals[proposal_id] = {
            "data": proposal_data,
            "approval_mode": approval_mode,
            "status": "pending",
        }
        if approval_mode == self.AUTO_APPROVED:
            return self.AUTO_APPROVED
        return self.APPROVAL_REQUIRED

    def _determine_approval_mode(self, proposal_data: dict[str, Any]) -> str:
        target = proposal_data.get("target", "")
        content = proposal_data.get("content", "")

        if not self._settings.enable_metacognition:
            return self.MANUAL_ONLY

        safe_targets = ["more_core/layers/l4_cognition.py", "more_core/router/layer_router.py"]
        if target in safe_targets and len(content) < 200:
            return self.AUTO_APPROVED
        return self.APPROVAL_REQUIRED

    def approve(self, proposal_id: str, approver_id: str) -> bool:
        if proposal_id not in self._pending_approvals:
            return False
        if approver_id not in self._approvers:
            return False
        self._pending_approvals[proposal_id]["status"] = "approved"
        self._pending_approvals[proposal_id]["approver"] = approver_id
        return True

    def reject(self, proposal_id: str, reason: str = "") -> bool:
        if proposal_id not in self._pending_approvals:
            return False
        self._pending_approvals[proposal_id]["status"] = "rejected"
        self._pending_approvals[proposal_id]["reject_reason"] = reason
        return True

    def get_status(self, proposal_id: str) -> dict[str, Any] | None:
        return self._pending_approvals.get(proposal_id)
