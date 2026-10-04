"""A2A (Agent-to-Agent) Protocol API router.

Exposes MoRE OS as an A2A-compatible agent that can receive tasks
from Codex CLI, Claude Code, or other A2A-speaking agents.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ...runtime.orchestrator import MoRECore
from ...security.rbac import Permission, require_permission
from ..auth import require_scope


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["A2A"])

    deps = [Depends(require_api_key)] if require_api_key else []
    write_deps = deps + [
        Depends(require_permission(Permission.TASK_EXECUTE)),
        Depends(require_scope("tasks:execute")),
    ]

    @router.post("/a2a", dependencies=write_deps)
    @router.post("/a2a/", dependencies=write_deps)
    async def a2a_endpoint(request: Request) -> Any:
        """A2A JSON-RPC endpoint — receives tasks from other agents."""
        body = await request.json()
        srv = core.a2a_server
        result = await srv.handle_request(body)
        return result

    @router.get("/a2a/agent-card", dependencies=deps)
    async def agent_card() -> dict[str, Any]:
        """Return this agent's capability card."""
        srv = core.a2a_server
        card = srv._agent_card
        return {
            "name": card.name,
            "description": card.description,
            "url": card.url,
            "version": card.version,
            "capabilities": card.capabilities,
            "skills": card.skills,
        }

    @router.get("/a2a/tasks", dependencies=deps)
    async def list_tasks() -> dict[str, Any]:
        """List active A2A tasks."""
        srv = core.a2a_server
        tasks = {}
        for tid, task in srv._tasks.items():
            tasks[tid] = {
                "id": task.id,
                "state": task.state.value,
                "message_count": len(task.messages),
            }
        return {"tasks": tasks, "count": len(tasks)}

    return router
