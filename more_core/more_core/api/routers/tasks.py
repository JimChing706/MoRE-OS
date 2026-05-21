"""Tasks router — task execution, status, history."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ...core.types import TaskRequest, TaskType
from ...runtime.orchestrator import MoRECore

# ---------------------------------------------------------------------------
# Shared task store (module-level so other routers can import it)
# ---------------------------------------------------------------------------

_task_store: Dict[str, dict] = {}


async def _execute_task_background(task_id: str, task_info: dict, core: MoRECore) -> None:
    """Background task executor with concurrency protection."""
    try:
        _task_store[task_id]["status"] = "in_progress"
        _task_store[task_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        req = TaskRequest(
            type=TaskType.NLP_TASK,
            query=task_info.get("description", task_info.get("title", "")),
            context=task_info.get("context", {}),
            timeout_s=180.0,
        )
        result = await core.execute(req)

        _task_store[task_id].update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": result.output,
            "progress": 100,
        })
    except Exception as e:
        _task_store[task_id].update({
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        })


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Tasks"])

    class TaskRequestPayload:
        """Inline model to avoid circular imports."""
        pass

    from pydantic import BaseModel, Field as _Field

    class Payload(BaseModel):
        type: TaskType = TaskType.NLP_TASK
        plugin_type: str | None = None
        query: str
        context: dict[str, Any] = _Field(default_factory=dict)
        require_metacognitive_monitoring: bool = False
        allow_self_improvement: bool = False
        target_layer: str | None = None
        timeout_s: float = 60.0

    @router.post("/tasks/execute", dependencies=[Depends(require_api_key)])
    async def execute(payload: Payload) -> dict[str, Any]:
        from ...core.types import LayerId
        target = LayerId(payload.target_layer) if payload.target_layer else None
        req = TaskRequest(
            type=payload.type,
            plugin_type=payload.plugin_type,
            query=payload.query,
            context=payload.context,
            target_layer=target,
            require_metacognitive_monitoring=payload.require_metacognitive_monitoring,
            allow_self_improvement=payload.allow_self_improvement,
            timeout_s=payload.timeout_s,
        )
        result = await core.execute(req)
        return result.model_dump()

    @router.get("/tasks/{task_id}/status")
    async def get_task_status(task_id: str) -> dict[str, Any]:
        if task_id not in _task_store:
            return {"status": "not_found", "error": "Task not found"}
        task = _task_store[task_id]
        return {
            "task_id": task_id,
            "status": task.get("status", "unknown"),
            "progress": task.get("progress", 0),
            "result": task.get("result"),
            "error": task.get("error"),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
        }

    @router.post("/tasks/{task_id}/execute", dependencies=[Depends(require_api_key)])
    async def execute_task(task_id: str) -> dict[str, Any]:
        if task_id not in _task_store:
            return {"status": "not_found", "error": "Task not found"}
        task = _task_store[task_id]
        if task.get("status") not in ["pending", "failed"]:
            return {"status": "invalid", "error": f"Task is already {task.get('status')}"}
        asyncio.create_task(_execute_task_background(task_id, task, core))
        return {"status": "started", "task_id": task_id, "message": "Task execution started"}

    @router.get("/tasks/history")
    async def get_task_history(limit: int = 20) -> dict[str, Any]:
        tasks = list(_task_store.values())[-limit:]
        return {
            "tasks": [
                {
                    "task_id": t.get("task_id"),
                    "title": t.get("title"),
                    "status": t.get("status"),
                    "result": t.get("result"),
                    "error": t.get("error"),
                    "created_at": t.get("created_at"),
                    "completed_at": t.get("completed_at"),
                }
                for t in tasks
            ]
        }

    return router


# Re-export for other routers that need the task store
__all__ = ["_task_store", "_execute_task_background", "create_router"]
