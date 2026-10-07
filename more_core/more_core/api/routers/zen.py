"""ZEN rules router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.get("/zen/rules")
    async def zen_rules() -> dict[str, Any]:
        from ...zen_rules import get_enforcer

        enforcer = get_enforcer()
        return {"rules": enforcer.list_rules()}

    @router.get("/zen/compliance")
    async def zen_compliance() -> Any:
        from ...zen_rules import get_enforcer

        enforcer = get_enforcer()
        return enforcer.get_compliance_report()

    @router.get("/zen/violations")
    async def zen_violations(severity: str | None = None) -> dict[str, Any]:
        from ...zen_rules import get_enforcer, RuleSeverity

        enforcer = get_enforcer()
        try:
            sev = RuleSeverity(severity) if severity else None
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid severity: {severity}")
        violations = enforcer.get_violations(sev)
        return {
            "violations": [
                {
                    "id": i,
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "severity": v.severity.value,
                    "category": v.category.value,
                    "timestamp": v.timestamp,
                    "resolved": v.resolved,
                    "resolution": v.resolution,
                }
                for i, v in enumerate(violations)
            ]
        }

    @router.post("/zen/violations/{violation_id}/resolve", dependencies=[Depends(require_api_key)])
    async def zen_resolve_violation(
        violation_id: int, resolution: dict[str, str]
    ) -> dict[str, Any]:
        from ...zen_rules import get_enforcer

        enforcer = get_enforcer()
        success = enforcer.resolve_violation(violation_id, resolution.get("resolution", ""))
        return {"success": success, "violation_id": violation_id}

    @router.get("/ontology/constraints")
    async def ontology_constraints() -> list[dict[str, Any]]:
        return [
            {
                "entity": c.entity.value,
                "rule_id": c.rule_id,
                "description": c.description,
                "priority": c.priority,
                "enforced": c.enforced,
            }
            for c in core.ontology.constraints()
        ]

    @router.get("/evolution/archive")
    async def evolution_archive() -> Any:
        return core.evolution_archive.stats()

    @router.get("/evolution/summary")
    async def evolution_summary(
        task_type: str | None = None,
        query_fp: str | None = None,
    ) -> Any:
        """Return the evolution signal dashboard snapshot.

        Mirrors :func:`more_core.codegen.evolution_signal.compute_evolution_summary`;
        accepts optional ``task_type`` and ``query_fp`` filters. Never raises
        on DB errors — a zeroed default shape is returned instead.
        """
        from ...codegen.evolution_signal import compute_evolution_summary

        try:
            project_root = getattr(getattr(core, "settings", None), "project_root", None) or None
        except Exception:
            project_root = None
        summary = compute_evolution_summary(
            task_type=task_type or "",
            query_fp=query_fp or "",
            project_root=project_root,
        )
        return summary

    return router
