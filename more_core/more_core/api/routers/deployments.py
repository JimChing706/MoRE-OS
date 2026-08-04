"""Deployments router — agent/service lifecycle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.get("/deployments")
    async def list_deployments(
        dtype: str | None = None, status: str | None = None
    ) -> dict[str, Any]:
        from ...deploy.manager import DeploymentType, DeploymentStatus

        dt = None
        ds = None
        if dtype:
            try:
                dt = DeploymentType(dtype)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid type: {dtype}")
        if status:
            try:
                ds = DeploymentStatus(status)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
        return {
            "deployments": core.deployment_manager.list_deployments(dt, ds),
            "stats": core.deployment_manager.stats(),
        }

    @router.post("/deployments", dependencies=[Depends(require_api_key)])
    async def create_deployment(payload: dict[str, Any]) -> Any:
        from ...deploy.manager import DeploymentType

        try:
            dtype = DeploymentType(payload.get("type", "hand"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid deployment type")
        dep = await core.deployment_manager.deploy(
            name=payload.get("name", "unnamed"),
            dtype=dtype,
            target_id=payload.get("target_id", ""),
            config=payload.get("config"),
            labels=payload.get("labels"),
            auto_restart=payload.get("auto_restart", True),
        )
        return dep.to_dict()

    @router.get("/deployments/{dep_id}")
    async def get_deployment(dep_id: str) -> Any:
        dep = core.deployment_manager.get(dep_id)
        if dep is None:
            raise HTTPException(status_code=404, detail=f"Deployment not found: {dep_id}")
        return dep.to_dict()

    @router.post("/deployments/{dep_id}/restart", dependencies=[Depends(require_api_key)])
    async def restart_deployment(dep_id: str) -> dict[str, Any]:
        ok = await core.deployment_manager.restart(dep_id)
        return {"success": ok, "dep_id": dep_id}

    @router.post("/deployments/{dep_id}/stop", dependencies=[Depends(require_api_key)])
    async def stop_deployment(dep_id: str) -> dict[str, Any]:
        ok = await core.deployment_manager.undeploy(dep_id)
        return {"success": ok, "dep_id": dep_id}

    @router.delete("/deployments/{dep_id}", dependencies=[Depends(require_api_key)])
    async def remove_deployment(dep_id: str) -> dict[str, Any]:
        ok = await core.deployment_manager.remove(dep_id)
        return {"success": ok, "dep_id": dep_id}

    return router
