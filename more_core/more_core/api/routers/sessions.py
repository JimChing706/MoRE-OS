"""Sessions router — user access management."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    deps = [Depends(require_api_key)] if require_api_key else []
    router = APIRouter(prefix="/api/v1")

    @router.post("/sessions", dependencies=deps)
    async def create_session(payload: dict[str, str]) -> Any:
        session = core.session_manager.create_session(
            user_id=payload.get("user_id", "anonymous"),
            user_name=payload.get("user_name", ""),
            role=payload.get("role", "viewer"),
            ip_address=payload.get("ip_address", ""),
        )
        return session.to_dict()

    @router.get("/sessions", dependencies=deps)
    async def list_sessions() -> dict[str, Any]:
        return {
            "sessions": core.session_manager.list_sessions(),
            "stats": core.session_manager.stats(),
        }

    @router.get("/sessions/{session_id}", dependencies=deps)
    async def get_session(session_id: str) -> Any:
        session = core.session_manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        session.touch()
        return session.to_dict()

    @router.delete("/sessions/{session_id}", dependencies=deps)
    async def destroy_session(session_id: str) -> dict[str, Any]:
        ok = core.session_manager.destroy_session(session_id)
        return {"success": ok, "session_id": session_id}

    @router.post("/sessions/{session_id}/subscribe", dependencies=deps)
    async def subscribe_session(session_id: str, payload: dict[str, str]) -> dict[str, Any]:
        topic = payload.get("topic", "")
        if not topic:
            raise HTTPException(status_code=422, detail="topic is required")
        ok = core.session_manager.subscribe(session_id, topic)
        return {"success": ok, "session_id": session_id, "topic": topic}

    @router.post("/sessions/{session_id}/unsubscribe", dependencies=deps)
    async def unsubscribe_session(session_id: str, payload: dict[str, str]) -> dict[str, Any]:
        topic = payload.get("topic", "")
        ok = core.session_manager.unsubscribe(session_id, topic)
        return {"success": ok, "session_id": session_id, "topic": topic}

    @router.get("/plugins", dependencies=deps)
    async def plugins() -> dict[str, Any]:
        return {
            "discovered": [asdict(md) for md in core.plugins.list()],
            "active": [md.name for md in core.plugins.active()],
        }

    return router
