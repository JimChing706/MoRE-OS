"""Skills router — modular capabilities."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...security.rbac import Permission, require_permission
from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.get("/skills")
    async def list_skills(category: str | None = None) -> dict[str, Any]:
        from ...skills.base import SkillCategory

        cat = None
        if category:
            try:
                cat = SkillCategory(category)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid category: {category}")
        skills = core.skill_manager.list_skills(cat)
        return {
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "category": s.category.value,
                    "version": s.version,
                    "tags": s.tags,
                    "usage_count": s.usage_count,
                    "success_rate": s.success_rate,
                }
                for s in skills
            ],
            "stats": core.skill_manager.get_stats(),
        }

    @router.post(
        "/skills/{skill_id}/run",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.HAND_RUN))],
    )
    async def run_skill(skill_id: str, params: dict[str, Any]) -> dict[str, Any]:
        result = await core.skill_manager.execute(skill_id, params)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    return router
