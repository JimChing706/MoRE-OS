"""Project Outputs router — task result to deliverable lifecycle.

Business chain:
  Task Execute → Task Complete → Auto-create Output → Store Output
  → List Outputs → Review Output → Feedback → Iterate → New Output

This router manages the complete output lifecycle, bridging task execution
results with project deliverables.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...runtime.orchestrator import MoRECore

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class OutputFile(BaseModel):
    path: str
    type: str
    lines: int = 0
    preview: str = ""


class OutputReview(BaseModel):
    rating: int = Field(ge=0, le=5)
    comments: str = ""
    approved: bool = False
    feedback: str = ""


class OutputIterationRequest(BaseModel):
    feedback: str
    target_improvements: list[str] = Field(default_factory=list)


class ProjectOutput(BaseModel):
    id: str
    name: str
    type: str
    status: str  # completed, pending_review, approved, needs_iteration
    created_at: str
    files: list[OutputFile] = Field(default_factory=list)
    tests: list[dict[str, Any]] = Field(default_factory=list)
    docs: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] | None = None
    iteration_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Output Store (in-memory + SQLite persistence)
# ---------------------------------------------------------------------------

_output_store: dict[str, dict[str, Any]] = {}
_DB_PATH = str(Path(__file__).resolve().parents[3] / "data" / "outputs.db")

_db_lock = threading.Lock()
_db_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Return the shared module-level connection (WAL, thread-safe via lock)."""
    global _db_conn
    if _db_conn is None:
        db_dir = Path(_DB_PATH).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outputs (
                id TEXT PRIMARY KEY,
                data JSON NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        _db_conn = conn
    return _db_conn


def _init_db() -> None:
    """Create outputs table if it doesn't exist."""
    with _db_lock:
        _get_conn().commit()


def _load_from_db() -> None:
    """Load existing outputs from SQLite into in-memory store on startup."""
    import json

    try:
        conn = _get_conn()
        rows = conn.execute("SELECT id, data FROM outputs ORDER BY created_at DESC").fetchall()
        for row_id, row_data in rows:
            _output_store[row_id] = json.loads(row_data)
        _log.info("Loaded %d outputs from %s", len(rows), _DB_PATH)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Could not load outputs from DB: %s", exc)


def _save_to_db(output_id: str, data: dict[str, Any]) -> None:
    """Persist a single output to SQLite (upsert)."""
    import json

    try:
        # Convert Pydantic models and other non-serializable objects to dicts
        serializable = _to_json_safe(data)
        with _db_lock:
            conn = _get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO outputs (id, data, created_at) VALUES (?, ?, ?)",
                (
                    output_id,
                    json.dumps(serializable, ensure_ascii=False),
                    data.get("created_at", ""),
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to persist output %s: %s", output_id, exc)


def _to_json_safe(obj: Any) -> Any:
    """Recursively convert Pydantic models and non-serializable objects to dicts/lists."""
    if hasattr(obj, "model_dump"):
        return _to_json_safe(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):
        return _to_json_safe(obj.dict())
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    return obj


def _delete_from_db(output_id: str) -> None:
    """Remove an output from SQLite."""
    try:
        with _db_lock:
            conn = _get_conn()
            conn.execute("DELETE FROM outputs WHERE id = ?", (output_id,))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.error("Failed to delete output %s: %s", output_id, exc)


# Init on module load
_init_db()
_load_from_db()


def _extract_files_from_output(output_text: str, task_type: str) -> list[OutputFile]:
    """Parse code blocks and documents from task output text."""
    files = []

    # Extract code blocks
    if "```" in output_text:
        code_blocks = re.findall(r"```(\w+)?\n(.*?)```", output_text, re.DOTALL)
        for idx, (lang, code) in enumerate(code_blocks):
            lang = lang or (
                "python"
                if any(kw in code for kw in ["def ", "class ", "import "])
                else "typescript"
            )
            files.append(
                OutputFile(
                    path=f"generated/{task_type}/file_{idx + 1}.{lang}",
                    type=lang,
                    lines=len(code.strip().split("\n")),
                    preview=code[:200] + ("..." if len(code) > 200 else ""),
                )
            )

    # Extract markdown documents
    if "# " in output_text or "## " in output_text:
        files.append(
            OutputFile(
                path=f"generated/{task_type}/README.md",
                type="markdown",
                lines=output_text.count("\n"),
                preview=output_text[:200] + ("..." if len(output_text) > 200 else ""),
            )
        )

    return files


def _auto_create_output(task_result: dict[str, Any]) -> ProjectOutput | None:
    """Automatically create an output from a completed task result."""
    try:
        task_id = task_result.get("task_id", "")
        output_text = task_result.get("output", "")
        metadata = task_result.get("metadata", {})
        task_type = metadata.get("task_type", task_result.get("type", "unknown"))

        if not output_text:
            return None

        files = _extract_files_from_output(output_text, task_type)

        output = {
            "id": f"out_{task_id}",
            "name": f"{metadata.get('task_label', task_type)}-{task_id[:8]}",
            "type": task_type,
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": [f.model_dump() for f in files],
            "tests": [],
            "docs": [],
            "review": None,
            "iteration_count": 0,
            "metadata": {
                "task_id": task_id,
                "performance": task_result.get("performance", {}),
                "layers": [
                    step.get("layer", "")
                    if isinstance(step, dict)
                    else (
                        step.layer.value if hasattr(step, "layer") else getattr(step, "layer", "")
                    )
                    for step in task_result.get("reasoning_chain", [])
                ],
                "output_preview": output_text[:500],
                "output_full": output_text,
            },
        }

        _output_store[output["id"]] = output
        _save_to_db(output["id"], output)
        _log.info("Auto-created output: %s from task %s", output["id"], task_id)
        return ProjectOutput(**output)

    except Exception as e:  # noqa: BLE001
        _log.error("Auto-create output failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        tags=["Project Outputs"],
        dependencies=[Depends(require_api_key)],
    )

    @router.get("/projects/outputs")
    async def list_outputs(limit: int = 50) -> dict[str, Any]:
        """List all project outputs, sorted by creation time (newest first)."""
        outputs = list(_output_store.values())
        outputs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {
            "outputs": outputs[:limit],
            "total": len(outputs),
        }

    @router.get("/projects/outputs/{output_id}")
    async def get_output(output_id: str) -> dict[str, Any]:
        """Get a single output by ID."""
        output = _output_store.get(output_id)
        if not output:
            raise HTTPException(status_code=404, detail=f"Output {output_id} not found")
        return {"output": output}

    @router.post("/projects/outputs/{output_id}/review", dependencies=[Depends(require_api_key)])
    async def review_output(output_id: str, review: OutputReview) -> dict[str, Any]:
        """Submit a review for an output.

        If approved, output status becomes 'approved'.
        If not approved, output status becomes 'needs_iteration'.
        """
        output = _output_store.get(output_id)
        if not output:
            raise HTTPException(status_code=404, detail=f"Output {output_id} not found")

        review_data = {
            "rating": review.rating,
            "comments": review.comments,
            "approved": review.approved,
            "feedback": review.feedback,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

        output["review"] = review_data
        output["status"] = "approved" if review.approved else "needs_iteration"
        output["metadata"]["review_summary"] = (
            f"Rating: {review.rating}/5, Approved: {review.approved}"
        )

        _output_store[output_id] = output
        _save_to_db(output_id, output)
        _log.info(
            "Output %s reviewed: approved=%s, rating=%d", output_id, review.approved, review.rating
        )

        return {
            "output": output,
            "message": "Review submitted successfully",
        }

    @router.post("/projects/outputs/{output_id}/iterate", dependencies=[Depends(require_api_key)])
    async def iterate_output(output_id: str, req: OutputIterationRequest) -> dict[str, Any]:
        """Create a new iteration of an output based on feedback.

        This triggers a new task execution with the feedback as context,
        producing an improved output.
        """
        output = _output_store.get(output_id)
        if not output:
            raise HTTPException(status_code=404, detail=f"Output {output_id} not found")

        # Build iteration query from feedback and original output
        original_output = output["metadata"].get("output_full", "")
        iteration_query = (
            f"Improve the following output based on this feedback:\n\n"
            f"Feedback: {req.feedback}\n\n"
            f"Target improvements: {', '.join(req.target_improvements)}\n\n"
            f"Original output:\n{original_output[:2000]}"
        )

        # Create new task for iteration
        from ...core.types import TaskRequest, TaskType

        task_req = TaskRequest(
            type=TaskType.CODE_GENERATION if "code" in output["type"] else TaskType.NLP_TASK,
            query=iteration_query,
            context={
                "iteration_of": output_id,
                "iteration_count": output.get("iteration_count", 0) + 1,
                "original_type": output["type"],
            },
            timeout_s=120.0,
        )

        result = await core.execute(task_req)

        # Create new output from iteration result
        new_output = _auto_create_output(
            {
                "task_id": f"iter_{output_id}_{output.get('iteration_count', 0) + 1}",
                "output": result.output,
                "type": output["type"],
                "metadata": {
                    "task_type": output["type"],
                    "task_label": f"{output['name']}-iter",
                    "iteration_of": output_id,
                    "iteration_count": output.get("iteration_count", 0) + 1,
                },
                "reasoning_chain": [],
                "performance": {},
            }
        )

        # Update original output iteration count
        output["iteration_count"] = output.get("iteration_count", 0) + 1
        output["status"] = "iterated"
        _output_store[output_id] = output
        _save_to_db(output_id, output)

        _log.info("Output %s iterated to %s", output_id, new_output.id if new_output else "failed")

        return {
            "original_output": output,
            "new_output": new_output.model_dump() if new_output else None,
            "message": "Iteration completed",
        }

    @router.delete("/projects/outputs/{output_id}", dependencies=[Depends(require_api_key)])
    async def delete_output(output_id: str) -> dict[str, Any]:
        """Delete an output."""
        if output_id not in _output_store:
            raise HTTPException(status_code=404, detail=f"Output {output_id} not found")

        del _output_store[output_id]
        _delete_from_db(output_id)
        _log.info("Output %s deleted", output_id)
        return {"message": f"Output {output_id} deleted"}

    @router.post("/projects/outputs/auto-create", dependencies=[Depends(require_api_key)])
    async def auto_create(task_result: dict[str, Any]) -> dict[str, Any]:
        """Manually trigger auto-creation of an output from a task result.

        This endpoint is called by the task execution pipeline when a task completes.
        """
        output = _auto_create_output(task_result)
        if not output:
            return {"output": None, "message": "No output created (empty task result)"}
        return {"output": output.model_dump(), "message": "Output created successfully"}

    return router


__all__ = ["_auto_create_output", "_output_store", "create_router"]
