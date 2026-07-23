"""Hands router — autonomous agent packages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...security.rbac import Permission, require_permission
from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/hands")
    async def list_hands() -> Any:
        return core.hands.stats()

    @router.get("/hands/registry")
    async def hands_registry() -> list[dict[str, Any]]:
        return [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "category": m.category,
                "schedule": m.schedule,
                "tools": m.tools,
                "skills": m.skills,
                "require_approval": m.require_approval,
            }
            for m in core.hand_registry.list_manifests()
        ]

    @router.post(
        "/hands/{hand_id}/activate",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def activate_hand(hand_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            hand = await core.hands.activate(hand_id, config)
            return {"success": True, "hand": hand.stats}
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/hands/{hand_id}/deactivate",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_DEACTIVATE)),
        ],
    )
    async def deactivate_hand(hand_id: str) -> dict[str, Any]:
        await core.hands.deactivate(hand_id)
        return {"success": True, "hand_id": hand_id}

    @router.post(
        "/hands/{hand_id}/pause",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def pause_hand(hand_id: str) -> dict[str, Any]:
        await core.hands.pause(hand_id)
        return {"success": True, "hand_id": hand_id}

    @router.post(
        "/hands/{hand_id}/resume",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def resume_hand(hand_id: str) -> dict[str, Any]:
        await core.hands.resume(hand_id)
        return {"success": True, "hand_id": hand_id}

    @router.post(
        "/hands/{hand_id}/run",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.HAND_RUN))],
    )
    async def run_hand(hand_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await core.hands.run_once(hand_id, context)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "tokens_used": result.tokens_used,
        }

    @router.get("/hands/{hand_id}/status")
    async def hand_status(hand_id: str) -> Any:
        hand = core.hands.get_hand(hand_id)
        if hand is None:
            raise HTTPException(status_code=404, detail=f"Hand not active: {hand_id}")
        return hand.stats

    @router.get("/hands/{hand_id}/results")
    async def hand_results(hand_id: str, limit: int = 10) -> dict[str, Any]:
        results = core.hands.get_results(hand_id, limit)
        return {
            "hand_id": hand_id,
            "results": [
                {
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                    "tokens_used": r.tokens_used,
                }
                for r in results
            ],
        }

    @router.post(
        "/hands/{hand_id}/save",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def save_hand(hand_id: str) -> dict[str, Any]:
        hand = core.hands.get_hand(hand_id)
        if hand is None:
            raise HTTPException(status_code=404, detail=f"Hand not active: {hand_id}")
        snapshot = core.hand_persistence.save(hand)
        return {"success": True, "hand_id": hand_id, "saved_at": snapshot.saved_at}

    @router.post(
        "/hands/{hand_id}/wakeup",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def wakeup_hand(hand_id: str) -> dict[str, Any]:
        snapshot = core.hand_persistence.load(hand_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"No saved state: {hand_id}")
        try:
            hand = await core.hands.activate(hand_id, snapshot.config)
            core.hand_persistence.restore(hand, snapshot)
            return {"success": True, "hand_id": hand_id, "restored_runs": snapshot.run_count}
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/hands/saved")
    async def list_saved_hands() -> dict[str, Any]:
        return {"saved_hands": core.hand_persistence.list_saved()}

    @router.post(
        "/hands/{source_id}/clone",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.HAND_ACTIVATE)),
        ],
    )
    async def clone_hand(source_id: str, payload: dict[str, Any] | None = None) -> Any:
        payload = payload or {}
        new_id = payload.get("new_id", f"{source_id}_clone")
        overrides = payload.get("config", {})
        result = await core.hand_cloner.clone(source_id, new_id, overrides)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Clone failed"))
        return result

    return router
