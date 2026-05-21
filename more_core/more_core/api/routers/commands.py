"""Commands router — unified slash command registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/commands")
    async def list_commands(surface: str | None = None) -> list[dict[str, Any]]:
        from ...commands.registry import CommandSurface
        sf = None
        if surface:
            try:
                sf = CommandSurface[surface.upper()]
            except KeyError:
                raise HTTPException(status_code=422, detail=f"Invalid surface: {surface}")
        return core.commands.to_api_dict(sf)

    @router.get("/commands/stats")
    async def commands_stats() -> dict[str, Any]:
        return core.commands.stats()

    return router
