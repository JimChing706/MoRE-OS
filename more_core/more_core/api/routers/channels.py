"""Channels router — message platform adapters."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    deps = [Depends(require_api_key)] if require_api_key else []

    @router.get("/channels", dependencies=deps)
    async def list_channels() -> dict[str, Any]:
        return {"channels": core.channels.list_channels(), "running": core.channels.is_running()}

    @router.get("/channels/status", dependencies=deps)
    async def channels_status() -> dict[str, Any]:
        status = core.channels.get_status()
        return {
            name: {
                "enabled": s.enabled,
                "running": s.running,
                "messages": s.messages_processed,
                "errors": s.errors,
            }
            for name, s in status.items()
        }

    @router.get("/channels/reconnect", dependencies=deps)
    async def reconnect_status() -> Any:
        return core.reconnect_manager.stats()

    @router.get("/channels/reconnect/states", dependencies=deps)
    async def reconnect_states() -> Any:
        return core.reconnect_manager.get_all_states()

    return router
