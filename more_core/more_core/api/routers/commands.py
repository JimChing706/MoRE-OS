"""Commands router — unified slash command registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    deps = [Depends(require_api_key)] if require_api_key else []

    @router.get("/commands", dependencies=deps)
    async def list_commands(surface: str | None = None) -> Any:
        from ...commands.registry import CommandSurface

        sf = None
        if surface:
            try:
                sf = CommandSurface[surface.upper()]
            except KeyError:
                raise HTTPException(status_code=422, detail=f"Invalid surface: {surface}")
        return core.commands.to_api_dict(sf)

    @router.get("/commands/stats", dependencies=deps)
    async def commands_stats() -> Any:
        return core.commands.stats()

    return router
