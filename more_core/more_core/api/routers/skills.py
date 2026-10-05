"""Skills router — modular capabilities."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...security.rbac import Permission, require_permission
from ...runtime.orchestrator import MoRECore


def _skill_to_dict(meta: Any, core: MoRECore) -> dict[str, Any]:
    """技能元数据 + 运行状态 + 真实执行指标（供 list / detail 复用）。"""
    skill = core.skill_manager.get(meta.id)
    status = skill.get_status().value if skill is not None else "unknown"
    return {
        "id": meta.id,
        "name": meta.name,
        "description": meta.description,
        "category": meta.category.value,
        "version": meta.version,
        "author": meta.author,
        "tags": list(meta.tags),
        "dependencies": list(meta.dependencies),
        "status": status,
        "usage_count": meta.usage_count,
        "success_rate": meta.success_rate,
        "avg_duration_ms": round(meta.avg_duration_ms, 1),
    }


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
            "skills": [_skill_to_dict(s, core) for s in skills],
            "stats": core.skill_manager.get_stats(),
        }

    @router.get("/skills/{skill_id}")
    async def get_skill(skill_id: str) -> dict[str, Any]:
        """单个技能详情：元数据 + 状态 + 健康 + 真实执行指标。"""
        skill = core.skill_manager.get(skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"Unknown skill: {skill_id}")
        payload = _skill_to_dict(skill.metadata, core)
        try:
            payload["healthy"] = await skill.health_check()
        except Exception:
            payload["healthy"] = False
        return {"status": "ok", "skill": payload}

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
