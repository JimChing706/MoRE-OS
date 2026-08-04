"""Hot-reload router — subsystem hot-reloading."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...security.rbac import Permission, require_permission
from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @router.post(
        "/reload/{scope}",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_CONFIG))],
    )
    async def hot_reload(scope: str) -> dict[str, Any]:
        from ...runtime.hot_reload import HotReloader, ReloadScope

        if not hasattr(core, "_hot_reloader"):
            core._hot_reloader = HotReloader(core)
        try:
            rs = ReloadScope(scope)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scope: {scope}. Valid: {[s.value for s in ReloadScope]}",
            )
        event = await core._hot_reloader.reload(rs)
        return {
            "scope": event.scope.value,
            "success": event.success,
            "error": event.error,
            "duration_ms": event.duration_ms,
            "changes": event.changes,
        }

    @router.post(
        "/reload",
        dependencies=[Depends(require_api_key), Depends(require_permission(Permission.SYS_CONFIG))],
    )
    async def hot_reload_all() -> list[dict[str, Any]]:
        from ...runtime.hot_reload import HotReloader

        if not hasattr(core, "_hot_reloader"):
            core._hot_reloader = HotReloader(core)
        events = await core._hot_reloader.reload_all()
        return [
            {
                "scope": e.scope.value,
                "success": e.success,
                "error": e.error,
                "duration_ms": e.duration_ms,
            }
            for e in events
        ]

    return router
