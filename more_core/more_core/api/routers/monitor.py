"""Monitor router — dashboard snapshot, full health, WebSocket."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/monitor/dashboard")
    async def dashboard_snapshot() -> dict[str, Any]:
        from .monitor import build_dashboard_snapshot
        return build_dashboard_snapshot(core)

    @router.get("/monitor/health")
    async def full_health() -> dict[str, Any]:
        import time as _time
        return {
            "status": "healthy",
            "uptime_s": round(_time.time() - core._start_time, 1),
            "subsystems": {
                "hands": {"registered": len(core.hand_registry.list_ids()), "active": len(core.hands.list_active())},
                "skills": core.skill_manager.get_stats(),
                "workflows": core.workflows.stats(),
                "deployments": core.deployment_manager.stats(),
                "schedules": {"jobs": len(core.cron.list_jobs())},
                "channels": {"count": len(core.channels.list_channels()), "running": core.channels.is_running()},
                "llm": {"providers": len(core.llm.list_providers()), "aliases": core.model_aliases.stats()["total_aliases"]},
                "security": {"rbac": core.rbac.enabled, "output_rules": core.output_filter.stats()["enabled_rules"]},
                "sessions": core.session_manager.stats(),
            },
        }

    @router.websocket("/monitor")
    async def ws_monitor(websocket):
        """WebSocket endpoint for real-time dashboard updates."""
        await websocket.accept()
        import asyncio as _aio
        from .monitor import build_dashboard_snapshot
        try:
            await websocket.send_json({"event": "snapshot", "data": build_dashboard_snapshot(core)})
            while True:
                await _aio.sleep(3)
                snapshot = build_dashboard_snapshot(core)
                await websocket.send_json({"event": "update", "data": snapshot})
        except Exception:
            pass

    return router
