"""Workflows router — multi-step orchestration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/workflows")
    async def list_workflows() -> dict[str, Any]:
        return {"workflows": core.workflows.list_workflows(), "stats": core.workflows.stats()}

    @router.post("/workflows", dependencies=[Depends(require_api_key)])
    async def create_workflow(payload: dict[str, Any]) -> dict[str, Any]:
        from ...workflows.engine import WorkflowDefinition, WorkflowStep, StepType
        steps = []
        for s in payload.get("steps", []):
            steps.append(WorkflowStep(
                id=s["id"], name=s.get("name", s["id"]),
                type=StepType(s.get("type", "task")),
                config=s.get("config", {}), depends_on=s.get("depends_on", []),
                timeout_s=s.get("timeout_s", 300), retry_count=s.get("retry_count", 0),
                condition=s.get("condition"),
            ))
        defn = WorkflowDefinition(
            id=payload.get("id", f"wf_{__import__('uuid').uuid4().hex[:8]}"),
            name=payload.get("name", "Unnamed Workflow"),
            description=payload.get("description", ""),
            steps=steps, variables=payload.get("variables", {}),
            schedule=payload.get("schedule"), tags=payload.get("tags", []),
        )
        core.workflows.register_workflow(defn)
        return {"success": True, "workflow_id": defn.id, "steps": len(defn.steps)}

    @router.post("/workflows/{workflow_id}/run", dependencies=[Depends(require_api_key)])
    async def start_workflow_run(workflow_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        try:
            run = await core.workflows.start_workflow(
                workflow_id, context=payload.get("context"),
                triggered_by=payload.get("triggered_by", "api"),
            )
            return run.to_summary()
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.get("/workflows/runs")
    async def list_workflow_runs(workflow_id: str | None = None, status: str | None = None, limit: int = 50) -> dict[str, Any]:
        from ...workflows.engine import WorkflowStatus
        ws = None
        if status:
            try:
                ws = WorkflowStatus(status)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        return {"runs": core.workflows.list_runs(workflow_id, ws, limit)}

    @router.get("/workflows/runs/{run_id}")
    async def get_workflow_run(run_id: str) -> dict[str, Any]:
        run = core.workflows.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return run.to_summary()

    @router.post("/workflows/runs/{run_id}/cancel", dependencies=[Depends(require_api_key)])
    async def cancel_workflow_run(run_id: str) -> dict[str, Any]:
        ok = await core.workflows.cancel_run(run_id)
        return {"success": ok, "run_id": run_id}

    @router.post("/workflows/runs/{run_id}/pause", dependencies=[Depends(require_api_key)])
    async def pause_workflow_run(run_id: str) -> dict[str, Any]:
        ok = await core.workflows.pause_run(run_id)
        return {"success": ok, "run_id": run_id}

    @router.post("/workflows/runs/{run_id}/resume", dependencies=[Depends(require_api_key)])
    async def resume_workflow_run(run_id: str) -> dict[str, Any]:
        ok = await core.workflows.resume_run(run_id)
        return {"success": ok, "run_id": run_id}

    return router
