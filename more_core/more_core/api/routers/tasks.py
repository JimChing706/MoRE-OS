"""Tasks router — task execution, status, history."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field as _Field

from ...security.rbac import Permission, require_permission
from ...core.types import TaskRequest, TaskType
from ...persistence.task_store import SQLiteTaskStore
from ...runtime.orchestrator import MoRECore

import os as _os


class ExecuteTaskPayload(BaseModel):
    """Request body for POST /tasks/execute."""

    type: TaskType = TaskType.NLP_TASK
    plugin_type: str | None = None
    query: str = _Field(max_length=16384)
    context: dict[str, Any] = _Field(default_factory=dict)
    require_metacognitive_monitoring: bool = False
    allow_self_improvement: bool = False
    target_layer: str | None = None
    timeout_s: float = 60.0


# ---------------------------------------------------------------------------
# Shared task store (module-level so other routers can import it)
# ---------------------------------------------------------------------------

_db_path = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "data", "tasks.db"
)
_db_norm = _os.path.normpath(_db_path)
try:
    _task_store = SQLiteTaskStore(_db_norm)
except Exception:
    # Fallback to /tmp when project data/ dir is TCC-protected
    _task_store = SQLiteTaskStore("/tmp/more_tasks.db")


async def _execute_task_background(task_id: str, task_info: dict[str, Any], core: MoRECore) -> None:
    """Background task executor with concurrency protection."""
    try:
        _task_store.update_task(
            task_id,
            {
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        req = TaskRequest(
            type=TaskType.NLP_TASK,
            query=task_info.get("description", task_info.get("title", "")),
            context=task_info.get("context", {}),
            timeout_s=180.0,
        )
        result = await core.execute(req)

        # Auto-create output from successful task result
        from .outputs import _auto_create_output

        _auto_create_output(
            {
                "task_id": task_id,
                "output": result.output,
                "type": req.type.value,
                "metadata": {
                    "task_type": req.type.value,
                    "task_label": req.type.value,
                },
                "reasoning_chain": [],
                "performance": {},
            }
        )

        _task_store.update_task(
            task_id,
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": result.output,
                "progress": 100,
            },
        )
    except Exception as e:
        _task_store.update_task(
            task_id,
            {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            },
        )


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Tasks"])

    @router.post(
        "/tasks/execute",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
        ],
    )
    async def execute(payload: ExecuteTaskPayload) -> dict[str, Any]:
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

        # Auto-create output from successful task result
        from .outputs import _auto_create_output

        _auto_create_output(
            {
                "task_id": result.task_id if hasattr(result, "task_id") else "task_auto",
                "output": result.output,
                "type": payload.type.value,
                "metadata": {
                    "task_type": payload.type.value,
                    "task_label": payload.query[:50],
                },
                "reasoning_chain": result.reasoning_chain
                if hasattr(result, "reasoning_chain")
                else [],
                "performance": result.performance if hasattr(result, "performance") else {},
            }
        )

        return result.model_dump()

    @router.get("/tasks/{task_id}/status")
    async def get_task_status(task_id: str) -> dict[str, Any]:
        task = _task_store.get_task(task_id)
        if task is None:
            return {"status": "not_found", "error": "Task not found"}
        return {
            "task_id": task_id,
            "status": task.get("status", "unknown"),
            "progress": task.get("progress", 0),
            "result": task.get("result"),
            "error": task.get("error"),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
        }

    @router.post(
        "/tasks/{task_id}/execute",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
        ],
    )
    async def execute_task(task_id: str) -> dict[str, Any]:
        task = _task_store.get_task(task_id)
        if task is None:
            return {"status": "not_found", "error": "Task not found"}
        if task.get("status") not in ["pending", "failed"]:
            return {"status": "invalid", "error": f"Task is already {task.get('status')}"}
        asyncio.create_task(_execute_task_background(task_id, task, core))
        return {"status": "started", "task_id": task_id, "message": "Task execution started"}

    @router.get("/tasks/history")
    async def get_task_history(limit: int = 20) -> dict[str, Any]:
        tasks = _task_store.list_tasks(limit=limit)
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

    @router.post(
        "/tasks/stream",
        dependencies=[
            Depends(require_api_key),
            Depends(require_permission(Permission.TASK_EXECUTE)),
        ],
    )
    async def stream_execute(payload: ExecuteTaskPayload) -> Any:
        """Stream task execution as Server-Sent Events (SSE)."""
        from fastapi.responses import StreamingResponse
        from ...core.types import TaskRequest as TR

        req = TR(
            type=payload.type,
            plugin_type=payload.plugin_type,
            query=payload.query,
            context=payload.context,
            timeout_s=payload.timeout_s,
        )
        return StreamingResponse(
            core.stream_execute(req),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


# Re-export for other routers that need the task store
__all__ = ["_task_store", "_execute_task_background", "create_router"]
