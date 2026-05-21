"""Sessions router — user access management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.post("/sessions")
    async def create_session(payload: dict[str, str]) -> dict[str, Any]:
        session = core.session_manager.create_session(
            user_id=payload.get("user_id", "anonymous"),
            user_name=payload.get("user_name", ""),
            role=payload.get("role", "viewer"),
            ip_address=payload.get("ip_address", ""),
        )
        return session.to_dict()

    @router.get("/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": core.session_manager.list_sessions(), "stats": core.session_manager.stats()}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = core.session_manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        session.touch()
        return session.to_dict()

    @router.delete("/sessions/{session_id}")
    async def destroy_session(session_id: str) -> dict[str, Any]:
        ok = core.session_manager.destroy_session(session_id)
        return {"success": ok, "session_id": session_id}

    @router.post("/sessions/{session_id}/subscribe")
    async def subscribe_session(session_id: str, payload: dict[str, str]) -> dict[str, Any]:
        topic = payload.get("topic", "")
        if not topic:
            raise HTTPException(status_code=422, detail="topic is required")
        ok = core.session_manager.subscribe(session_id, topic)
        return {"success": ok, "session_id": session_id, "topic": topic}

    @router.post("/sessions/{session_id}/unsubscribe")
    async def unsubscribe_session(session_id: str, payload: dict[str, str]) -> dict[str, Any]:
        topic = payload.get("topic", "")
        ok = core.session_manager.unsubscribe(session_id, topic)
        return {"success": ok, "session_id": session_id, "topic": topic}

    @router.get("/plugins")
    async def plugins() -> dict[str, Any]:
        return {
            "discovered": [md.__dict__ for md in core.plugins.list()],
            "active": [md.name for md in core.plugins.active()],
        }

    return router
