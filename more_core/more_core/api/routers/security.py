"""Security router — RBAC, taint tracking, output filter, incidents."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore
from ...security.rbac import Permission, require_permission


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.get("/security/audit")
    async def audit_logs(limit: int = 50) -> dict[str, Any]:
        records = core.audit.read_recent(limit)
        return {"records": records, "total": len(records)}

    @router.get("/security/status")
    async def security_status() -> dict[str, Any]:
        return {
            "layers": [
                {
                    "id": 1,
                    "name": "API Authentication",
                    "status": "active" if os.getenv("MORE_API_KEY") else "dev_mode",
                },
                {"id": 2, "name": "RBAC", "status": "active" if core.rbac.enabled else "disabled"},
                {"id": 3, "name": "Input Validation", "status": "active"},
                {"id": 4, "name": "Path Traversal Protection", "status": "active"},
                {"id": 5, "name": "Command Injection Prevention", "status": "active"},
                {"id": 6, "name": "Sandbox Isolation", "status": "active"},
                {"id": 7, "name": "Rate Limiting", "status": "active"},
                {"id": 8, "name": "Circuit Breaker", "status": "active"},
                {"id": 9, "name": "Secret Redaction", "status": "active"},
                {"id": 10, "name": "Audit Logging", "status": "active"},
                {"id": 11, "name": "Policy Enforcement", "status": "active"},
                {"id": 12, "name": "ZEN Rules", "status": "active"},
                {"id": 13, "name": "Incident Response", "status": "active"},
                {"id": 14, "name": "Taint Tracking", "status": "active"},
                {"id": 15, "name": "Request Signing", "status": "available"},
                {"id": 16, "name": "Output Filtering", "status": "active"},
            ],
            "rbac": core.rbac.stats(),
            "taint": core.taint_tracker.stats(),
            "output_filter": core.output_filter.stats(),
        }

    @router.get("/security/rbac/roles")
    async def rbac_roles() -> Any:
        return core.rbac.list_roles()

    @router.post(
        "/security/rbac/assign",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_ADMIN))],
    )
    async def rbac_assign(payload: dict[str, str]) -> dict[str, Any]:
        user_id = payload.get("user_id", "")
        role = payload.get("role", "")
        if not user_id or not role:
            raise HTTPException(status_code=422, detail="user_id and role required")
        ok = core.rbac.assign_role(user_id, role)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        return {"success": True, "user_id": user_id, "role": role}

    @router.get("/security/taint")
    async def taint_status() -> Any:
        return core.taint_tracker.stats()

    @router.get("/security/taint/violations")
    async def taint_violations() -> Any:
        return core.taint_tracker.get_violations()

    @router.get("/security/output-filter/stats")
    async def output_filter_stats() -> Any:
        return core.output_filter.stats()

    @router.post(
        "/security/output-filter/scan",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_ADMIN))],
    )
    async def output_filter_scan(payload: dict[str, str]) -> dict[str, Any]:
        text = payload.get("text", "")
        findings = core.output_filter.scan(text)
        return {"findings": findings, "safe": len(findings) == 0}

    @router.get("/incidents")
    async def incidents(severity: str | None = None) -> dict[str, Any]:
        from ...incident_response import Severity

        try:
            sev = Severity(severity) if severity else None
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid severity: {severity}")
        active = core._incident_manager.get_active_incidents(sev)
        return {
            "incidents": [
                {
                    "id": i.id,
                    "type": i.incident_type.value,
                    "severity": i.severity.value,
                    "layer": i.layer.value,
                    "timestamp": i.timestamp,
                    "description": i.description,
                    "resolved": i.resolved,
                }
                for i in active
            ],
            "stats": core._incident_manager.get_incident_stats(),
        }

    @router.post(
        "/incidents/{incident_id}/resolve",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.GOV_RESOLVE)),
        ],
    )
    async def resolve_incident(incident_id: str, resolution: dict[str, str]) -> dict[str, Any]:
        success = await core._incident_manager.resolve_incident(
            incident_id, resolution.get("resolution", "")
        )
        return {"success": success, "incident_id": incident_id}

    # -- P1-4 G-2 覃朗：前版梯子运行时回滚端点 (内存态 toggle, 重启清零) --------
    @router.post(
        "/ops/tier_rollback",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.SYS_ADMIN)),
        ],
    )
    async def tier_rollback() -> dict[str, Any]:
        """RBAC 受控：SYS_ADMIN 权限。调用路由器 apply_previous_tier_ladder()
        将 T0~T3 四元组梯子在"当前版 <-> MORE_PREV_TIER_*_MODEL 前版"之间做
        内存态 toggle。长度不一致 (≠4 tiers) 时拒绝回滚，返回 reason 字段。
        """
        return dict(core.task_model_router.apply_previous_tier_ladder())

    return router
