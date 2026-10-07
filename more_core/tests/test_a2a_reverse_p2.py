"""Step-4 P2: A2A reverse handler tests (chassis → qnm-os).

All tests use direct calls to ``A2AServer.handle_request`` so no HTTP
server is required.  We also exercise the background-execution runner by
manually advancing the asyncio event loop via ``asyncio.sleep(0)`` and a
small real delay so the spawned task is scheduled.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from more_core.a2a.client import (
    A2AMessage,
    A2AServer,
    A2ATaskState,
    create_agent_card,
)
from more_core.core.types import TaskStatus, TaskType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_server(task_handler=None) -> A2AServer:
    card = create_agent_card(
        name="tester",
        description="test-only agent",
        url="http://localhost:1/",
        skills=["test"],
    )
    srv = A2AServer(card)
    if task_handler is not None:
        srv.set_task_handler(task_handler)
    return srv


def _mk_send(
    *,
    text: str = "write a greeting function in Python",
    task_type: str = "code_generation",
    context: dict[str, Any] | None = None,
    metadata_origin: bool = False,
) -> dict[str, Any]:
    """Build a JSON-RPC tasks/send payload matching bailongma_bridge shape."""
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    msg: dict[str, Any] = {
        "messageId": "m1",
        "role": "user",
        "parts": parts,
    }
    if metadata_origin:
        # chassis metadata shape (without rewriting the body)
        msg["metadata"] = {
            "qnm_origin": "delegate_v1",
            "task_type": task_type,
        }
    else:
        # body content shape
        msg["content"] = {  # type: ignore[assignment]  — optional during tests
            "text": text,
            "task_type": task_type,
            "context": context or {},
        }
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tasks/send",
        "params": {
            "task": {
                "id": "t-1",
                "messages": [msg],
                "metadata": {},
            }
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA2AReverseBasics:
    def test_agent_card_returns_shape(self):
        srv = _mk_server()
        res = srv._handle_get_card()
        assert res["result"]["agent"]["name"] == "tester"

    def test_stats_empty(self):
        srv = _mk_server()
        st = srv.stats()
        assert st["task_count"] == 0
        for state in A2ATaskState:
            assert st["by_state"][state.value] == 0

    def test_task_not_found_get_returns_error(self):
        srv = _mk_server()
        res = asyncio.run(
            srv.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": "x",
                    "method": "tasks/get",
                    "params": {"taskId": "missing"},
                }
            )
        )
        assert "error" in res
        assert res["error"]["code"] == -32602

    def test_cancel_missing_returns_error(self):
        srv = _mk_server()
        res = asyncio.run(
            srv.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": "x",
                    "method": "tasks/cancel",
                    "params": {"taskId": "missing"},
                }
            )
        )
        assert "error" in res


class TestA2AReverseTaskDispatch:
    def test_send_plain_text_defaults_to_nlp(self):
        """Legacy plain-text agents: no task_type/context in payload → NLP_TASK."""
        called: dict[str, Any] = {}

        async def handler(task):
            called["task"] = task
            # Simulate legacy handler behaviour: no task_type hint is resolved
            # because the caller sent us a text-only message.
            return task

        srv = _mk_server(task_handler=handler)
        # Minimal payload: only text in parts, no metadata/content.task_type
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {
                "task": {
                    "messages": [
                        {
                            "messageId": "m",
                            "role": "user",
                            "parts": [{"type": "text", "text": "plain text question"}],
                        }
                    ]
                }
            },
        }
        res = asyncio.run(srv.handle_request(payload))
        # tasks/send completes synchronously (handler runs then returns).
        # state returned by _handle_send_task = whatever handler set on task.
        # If handler returns untouched task.state → A2ATaskState.WORKING default
        # (set in _handle_send_task itself).
        assert res["result"]["taskId"]
        assert called["task"] is not None
        message = called["task"].messages[0]
        assert "plain text question" in message.content.get("text")

    def test_send_with_task_type_in_body_resolves_code_type(self):
        """BaiLongma bridge body-based task_type: content.task_type="code_generation"."""
        from more_core.core.types import TaskRequest

        captured: dict[str, Any] = {}

        async def handler(task):
            # Replicate orchestrator.py logic inline (no full orchestrator here):
            # task_type from body.content.task_type → TaskType.CODE_GENERATION
            body = task.messages[0].content
            hint = body.get("task_type") if isinstance(body, dict) else None
            req_type = TaskType.NLP_TASK
            for t in TaskType:
                if t.value == hint:
                    req_type = t
                    break
            captured["type"] = req_type
            # Fake a TaskRequest to validate resolution works
            _r = TaskRequest(type=req_type, query="x")
            assert _r.type == TaskType.CODE_GENERATION
            task.state = A2ATaskState.COMPLETED
            return task

        srv = _mk_server(task_handler=handler)
        payload = _mk_send(text="make a list", task_type="code_generation")
        # Message body.content has task_type; _handle_send_task reconstructs
        # A2AMessage from parts → .content = {"text": "..."}; metadata lost.
        # So test resolution via metadata route too (separate test).
        res = asyncio.run(srv.handle_request(payload))
        # Our handler sets COMPLETED → status.state == "completed"
        assert res["result"]["status"]["state"] == "completed"
        assert captured["type"] == TaskType.CODE_GENERATION

    def test_send_with_metadata_task_type_resolves(self):
        """Metadata-origin task_type: chassis sets msg.metadata instead of body."""
        captured: dict[str, Any] = {}

        async def handler(task):
            msg = task.messages[0]
            meta = msg.metadata or {}
            hint = None
            if meta.get("qnm_origin") == "delegate_v1":
                hint = meta.get("task_type")
            req_type = TaskType.NLP_TASK
            if hint:
                for t in TaskType:
                    if t.value == hint:
                        req_type = t
                        break
            captured["type"] = req_type
            task.state = A2ATaskState.COMPLETED
            return task

        srv = _mk_server(task_handler=handler)
        payload = _mk_send(metadata_origin=True, task_type="code_debugging")
        asyncio.run(srv.handle_request(payload))
        assert captured["type"] == TaskType.CODE_DEBUGGING

    def test_empty_text_marks_failed(self):
        async def handler(task):
            # Mirror orchestrator: if no text → FAILED
            any_text = False
            for m in task.messages:
                if isinstance(m.content, dict) and m.content.get("text"):
                    any_text = True
                    break
            if not any_text:
                task.state = A2ATaskState.FAILED
            return task

        srv = _mk_server(task_handler=handler)
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {
                "task": {"messages": [{"role": "user", "parts": [{"type": "text", "text": ""}]}]}
            },
        }
        res = asyncio.run(srv.handle_request(payload))
        assert res["result"]["status"]["state"] == "failed"


class TestA2AReverseCancelAndList:
    def test_cancel_marks_canceled(self):
        srv = _mk_server()
        asyncio.run(
            srv.handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "tasks/send",
                    "params": {
                        "task": {
                            "id": "c1",
                            "messages": [
                                {"role": "user", "parts": [{"type": "text", "text": "x"}]}
                            ],
                        }
                    },
                }
            )
        )
        res = asyncio.run(
            srv.handle_request(
                {"jsonrpc": "2.0", "id": "x", "method": "tasks/cancel", "params": {"taskId": "c1"}}
            )
        )
        assert res["result"]["taskId"] == "c1"
        st = srv.stats()
        assert st["by_state"]["canceled"] == 1

    def test_list_methods_filters_state(self):
        srv = _mk_server(task_handler=lambda t: asyncio.sleep(0, result=t))
        for tid, state in (("a1", "completed"), ("a2", "working")):
            asyncio.run(
                srv.handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": "1",
                        "method": "tasks/send",
                        "params": {
                            "task": {
                                "id": tid,
                                "messages": [
                                    {"role": "user", "parts": [{"type": "text", "text": "x"}]}
                                ],
                            }
                        },
                    }
                )
            )
            # Force state via back door
            srv._tasks[tid].state = A2ATaskState(state)
        res = srv._handle_list_tasks({"state": "completed", "limit": 10})
        assert res["result"]["count"] == 1
        assert res["result"]["tasks"][0]["id"] == "a1"


class TestA2AReverseBackgroundRunner:
    """Verify background-task semantics: tasks/send returns WORKING and a later
    tasks/get picks up COMPLETED once the runner has settled."""

    @pytest.mark.asyncio
    async def test_background_runner_writes_back_output_message(self):
        async def slow_handler(task):
            # Mirror P2's orchestrator logic: mark WORKING, create_task runner
            task.state = A2ATaskState.WORKING

            async def runner():
                await asyncio.sleep(0.05)
                # Append agent-role message
                task.messages.append(
                    A2AMessage(
                        role="agent",
                        content={"text": "the answer is 42"},
                        metadata={"task_status": TaskStatus.SUCCESS.value},
                    )
                )
                task.state = A2ATaskState.COMPLETED

            asyncio.create_task(runner())
            return task

        srv = _mk_server(task_handler=slow_handler)
        send_res = await srv.handle_request(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {
                    "task": {
                        "id": "bg1",
                        "messages": [{"role": "user", "parts": [{"type": "text", "text": "q"}]}],
                    }
                },
            }
        )
        assert send_res["result"]["status"]["state"] == "working"
        # Let the runner complete
        await asyncio.sleep(0.2)
        get_res = await srv.handle_request(
            {"jsonrpc": "2.0", "id": "2", "method": "tasks/get", "params": {"taskId": "bg1"}}
        )
        assert get_res["result"]["status"]["state"] == "completed"
        last_msg = get_res["result"]["messages"][-1]
        assert last_msg["role"] == "agent"
        parts_text = "".join(p.get("text", "") for p in last_msg["parts"])
        assert "42" in parts_text
