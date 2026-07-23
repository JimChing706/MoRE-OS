"""Cron router — scheduled tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...security.rbac import Permission, require_permission
from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/schedules")
    async def list_schedules() -> dict[str, Any]:
        jobs = core.cron.list_jobs()
        return {
            "jobs": [
                {
                    "job_id": j.job_id,
                    "name": j.name,
                    "schedule": j.schedule,
                    "enabled": j.enabled,
                    "last_run": j.last_run,
                    "next_run": j.next_run,
                    "run_count": j.run_count,
                    "description": j.description,
                }
                for j in jobs
            ]
        }

    @router.post(
        "/schedules/{job_id}/run",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_CONFIG))],
    )
    async def run_schedule(job_id: str) -> dict[str, Any]:
        result = await core.cron.run_job(job_id)
        return {
            "job_id": result.job_id,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    @router.post(
        "/schedules/{job_id}/enable",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_CONFIG))],
    )
    async def enable_schedule(job_id: str) -> dict[str, Any]:
        return {"success": core.cron.enable_job(job_id)}

    @router.post(
        "/schedules/{job_id}/disable",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_CONFIG))],
    )
    async def disable_schedule(job_id: str) -> dict[str, Any]:
        return {"success": core.cron.disable_job(job_id)}

    return router
