"""P3 E2E tests — FastAPI TestClient drives real HTTP POST / GET against
``/api/v1/a2a`` routes.

All tests use the synchronous ``fastapi.testclient.TestClient`` wrapper
around ``httpx`` so ASGI is exercised end-to-end (HTTP layer + router +
A2AServer.handle_request + orchestrator _a2a_handler + async runner).

Tests are deliberately scoped to ``/api/v1/a2a`` only; they assume the
MoRECore has the ``_FakeLLMProvider`` installed so no real LLM is needed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app
from more_core.core.config import Settings
from more_core.runtime.orchestrator import MoRECore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_core_with_custom_handler(task_handler):
    """Build MoRECore + force custom handler over a2a_server."""
    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
        codegen_candidates=1,
        codegen_review=False,
    )
    core = MoRECore(settings)
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]
    # Override default orchestrator handler with one injected by tests
    if task_handler is not None:
        core.a2a_server.set_task_handler(task_handler)
    return core


@pytest.fixture
def fast_client(request) -> Iterator[TestClient]:
    """TestClient over create_app() — support per-test handler override via
    ``request.node.callspec.params.get("task_handler", None)``.

    Default handler just sets state=COMPLETED synchronously for simple tests.
    """
    task_handler = getattr(request, "param", None)
    if task_handler is None:

        async def _handler(task):
            from more_core.a2a.client import A2AMessage, A2ATaskState

            task.state = A2ATaskState.WORKING

            # Micro background step to emulate async runner pattern used by
            # the real orchestrator handler.
            async def _runner():
                await asyncio.sleep(0.01)
                task.state = A2ATaskState.COMPLETED
                task.messages.append(
                    A2AMessage(
                        role="agent",
                        content={"text": "hello from a2a"},
                        metadata={"ok": True},
                    )
                )

            asyncio.create_task(_runner())
            return task

        task_handler = _handler
    core = _mk_core_with_custom_handler(task_handler)
    app = create_app(core)
    with TestClient(app) as c:
        c._core = core  # stash for tests that inspect the server directly
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


RPCID = "rpc-1"


def _payload_send(
    text: str = "hello",
    task_id: str = "t-http-1",
    *,
    task_type: str | None = None,
    metadata_task_type: bool = False,
    text_only: bool = False,
) -> dict:
    """Build a JSON-RPC tasks/send body mirroring BaiLongma bridge format."""
    msg: dict = {
        "messageId": "m1",
        "role": "user",
        "parts": [{"type": "text", "text": text}],
    }
    if not text_only:
        if metadata_task_type and task_type:
            msg["metadata"] = {"qnm_origin": "delegate_v1", "task_type": task_type}
            msg["content"] = {"text": text, "context": {}}
        else:
            body = {"text": text, "context": {}}
            if task_type:
                body["task_type"] = task_type
            msg["content"] = body
    return {
        "jsonrpc": "2.0",
        "id": RPCID,
        "method": "tasks/send",
        "params": {"task": {"id": task_id, "messages": [msg], "metadata": {}}},
    }


def _payload_get(task_id: str) -> dict:
    return {"jsonrpc": "2.0", "id": RPCID, "method": "tasks/get", "params": {"taskId": task_id}}


def _payload_cancel(task_id: str) -> dict:
    return {"jsonrpc": "2.0", "id": RPCID, "method": "tasks/cancel", "params": {"taskId": task_id}}


def _poll_until(client: TestClient, task_id: str, *, done_states, max_wait_s: float = 3.0):
    """tasks/get busy-loop until state falls into ``done_states``."""
    dead = time.time() + max_wait_s
    last = None
    while time.time() < dead:
        resp = client.post("/api/v1/a2a", json=_payload_get(task_id))
        assert resp.status_code == 200, resp.text
        last = resp.json()
        assert "result" in last, last
        state = last["result"]["status"]["state"]
        if state in done_states:
            return last
        time.sleep(0.05)
    pytest.fail(f"Poll timeout. Last response: {last!r}")


# ---------------------------------------------------------------------------
# 10 tests
# ---------------------------------------------------------------------------


class TestA2AHttpBasics:
    """Test HTTP layer for /api/v1/a2a routes."""

    def test_01_post_tasks_send_returns_working_id(self, fast_client):
        """[E2E #1] tasks/send via HTTP returns id + state=working."""
        resp = fast_client.post("/api/v1/a2a", json=_payload_send())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("jsonrpc") == "2.0"
        # id is intentionally echoed as empty string by A2AServer.
        assert "id" in body
        assert "result" in body
        assert body["result"]["taskId"] == "t-http-1"
        assert body["result"]["status"]["state"] in ("working", "completed")

    def test_02_send_then_poll_get_reaches_completed(self, fast_client):
        """[E2E #2] tasks/send → tasks/get poll reaches COMPLETED + output message."""
        send_resp = fast_client.post("/api/v1/a2a", json=_payload_send(task_id="t-poll-2"))
        assert send_resp.status_code == 200
        done = _poll_until(fast_client, "t-poll-2", done_states={"completed", "failed"})
        assert done["result"]["status"]["state"] == "completed"
        msgs = done["result"].get("messages", [])
        # last agent-role message has output text (serialised as parts[].text)
        agent_msgs = [m for m in msgs if m.get("role") == "agent"]
        assert agent_msgs, f"No agent msgs in {msgs!r}"
        last_parts_text = agent_msgs[-1]["parts"][0]["text"]
        assert "hello from a2a" in last_parts_text

    def test_03_cancel_missing_task_returns_rpc_error(self, fast_client):
        """[E2E #3] tasks/cancel on unknown taskId returns JSON-RPC error code."""
        resp = fast_client.post("/api/v1/a2a", json=_payload_cancel("t-not-exist"))
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body, f"Expected error in {body!r}"
        # A2AServer uses code=-32602 for missing-task errors
        assert body["error"]["code"] == -32602

    def test_04_list_tasks_http_route(self, fast_client):
        """[E2E #4] GET /api/v1/a2a/tasks returns the tasks just submitted."""
        fast_client.post("/api/v1/a2a", json=_payload_send(task_id="t-list-a"))
        fast_client.post("/api/v1/a2a", json=_payload_send(task_id="t-list-b"))
        resp = fast_client.get("/api/v1/a2a/tasks")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["count"] >= 2, data
        tasks = data["tasks"]
        assert "t-list-a" in tasks and "t-list-b" in tasks
        # Structure check
        for tid in ("t-list-a", "t-list-b"):
            assert isinstance(tasks[tid]["state"], str)
            assert "message_count" in tasks[tid]

    def test_05_agent_card_route(self, fast_client):
        """[E2E #5] GET /api/v1/a2a/agent-card returns expected card fields."""
        resp = fast_client.get("/api/v1/a2a/agent-card")
        assert resp.status_code == 200, resp.text
        card = resp.json()
        assert card["name"] == "QNMing MoRE OS"
        assert "Neuro-Symbolic" in card["description"]
        assert card["url"] == "http://localhost:8011"
        # capabilities is a dict in A2AAgentCard
        assert isinstance(card["capabilities"], dict)
        assert "code_gen" in card["skills"]

    def test_06_send_empty_text_fails_fast(self, fast_client):
        """[E2E #6] tasks/send with only empty text → handler returns FAILED.

        This uses a handler that mirrors orchestrator._a2a_handler behaviour
        of marking empty-text tasks FAILED immediately.
        """

        async def _empty_check_handler(task):
            from more_core.a2a.client import A2ATaskState

            text = ""
            for m in task.messages:
                body = m.content or {}
                t = body.get("text", "") if isinstance(body, dict) else ""
                if t:
                    text = t
            if not text:
                task.state = A2ATaskState.FAILED
            return task

        core = _mk_core_with_custom_handler(_empty_check_handler)
        with TestClient(create_app(core)) as c:
            resp = c.post(
                "/api/v1/a2a",
                json=_payload_send(text="", task_id="t-empty-6"),
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["result"]["status"]["state"] == "failed"

    def test_07_unknown_rpc_method_returns_error(self, fast_client):
        """[E2E #7] method "tasks/nope" → JSON-RPC -32601 method-not-found."""
        resp = fast_client.post(
            "/api/v1/a2a",
            json={"jsonrpc": "2.0", "id": "z", "method": "tasks/nope", "params": {}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == -32601

    def test_08_wrong_method_on_send_returns_error(self, fast_client):
        """[E2E #8] tasks/get called without required taskId field → A2AServer
        returns error with -32602 Invalid Params (verifies HTTP malformed
        parameter rejection path)."""
        resp = fast_client.post(
            "/api/v1/a2a",
            json={"jsonrpc": "2.0", "id": "bad", "method": "tasks/get", "params": {}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body, f"Expected error in {body!r}"
        assert body["error"]["code"] == -32602

    def test_09_body_task_type_routed_to_handler(self, fast_client):
        """[E2E #9] body.content.task_type is reachable inside the handler.

        We inject a handler that records body.task_type and echoes it back as
        output text so we can poll and assert it round-trips via HTTP.
        """
        recorded: dict = {}

        async def _record_handler(task):
            import asyncio as _aio

            from more_core.a2a.client import A2AMessage, A2ATaskState

            task.state = A2ATaskState.WORKING

            async def _runner():
                await _aio.sleep(0.01)
                m = task.messages[0]
                body = m.content if isinstance(m.content, dict) else {}
                recorded["task_type"] = body.get("task_type")
                task.state = A2ATaskState.COMPLETED
                task.messages.append(
                    A2AMessage(
                        role="agent",
                        content={"text": f"type={body.get('task_type')}"},
                    )
                )

            _aio.create_task(_runner())
            return task

        core = _mk_core_with_custom_handler(_record_handler)
        with TestClient(create_app(core)) as c:
            send = c.post(
                "/api/v1/a2a",
                json=_payload_send(
                    text="build api", task_id="t-body-type-9", task_type="code_generation"
                ),
            )
            assert send.status_code == 200
            done = _poll_until(c, "t-body-type-9", done_states={"completed"})
            assert recorded["task_type"] == "code_generation"
            last_agent = [m for m in done["result"]["messages"] if m["role"] == "agent"][-1]
            agent_text = last_agent["parts"][0]["text"]
            assert "type=code_generation" in agent_text

    def test_10_metadata_task_type_route(self, fast_client):
        """[E2E #10] metadata.qnm_origin=delegate_v1 + metadata.task_type is
        parsed correctly by an orchestrator-style handler, confirming HTTP
        headers → JSON → A2AMessage.metadata passes through end-to-end.
        """
        captured: dict = {}

        async def _meta_handler(task):
            import asyncio as _aio

            from more_core.a2a.client import A2AMessage, A2ATaskState

            task.state = A2ATaskState.WORKING

            async def _runner():
                await _aio.sleep(0.01)
                m = task.messages[0]
                meta = m.metadata if isinstance(m.metadata, dict) else {}
                tt = None
                if meta.get("qnm_origin") == "delegate_v1":
                    tt = meta.get("task_type")
                captured["task_type"] = tt
                task.state = A2ATaskState.COMPLETED
                task.messages.append(
                    A2AMessage(
                        role="agent",
                        content={"text": f"meta_tt={tt}"},
                    )
                )

            _aio.create_task(_runner())
            return task

        core = _mk_core_with_custom_handler(_meta_handler)
        with TestClient(create_app(core)) as c:
            send = c.post(
                "/api/v1/a2a",
                json=_payload_send(
                    text="audit logs",
                    task_id="t-meta-10",
                    task_type="reasoning",
                    metadata_task_type=True,
                ),
            )
            assert send.status_code == 200
            done = _poll_until(c, "t-meta-10", done_states={"completed"})
            assert captured["task_type"] == "reasoning"
            last_agent = [m for m in done["result"]["messages"] if m["role"] == "agent"][-1]
            agent_text = last_agent["parts"][0]["text"]
            assert "meta_tt=reasoning" in agent_text
