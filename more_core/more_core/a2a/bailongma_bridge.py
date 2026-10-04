"""Step-4 P0: BaiLongma Fusion A2A Bridge v1.

Minimal 3-message contract over existing A2AClient:

  1. ``ping()``        -> bool       : /health handshake, <= 5s timeout.
  2. ``echo(text)``    -> str        : round-trip liveness, proves JSON-RPC
                                       serialization path works both ways.
  3. ``delegate_task()`` -> A2ATask  : submits a code-family task to the
                                       BaiLongma chassis (the "brain" calls
                                       back into us later over the same
                                       reverse A2A handler we already expose).

Design rules from BAILONGMA_FUSION_V2_AUDIT:
  * A2A-over-HTTP **main line**; PyO3 deferred to P2+ (B1 default answer).
  * Two-process sidecar is the norm in dev mode; process manager only ships
    at P1.
  * Every public API is **best-effort, never raises**.  Returns ``None`` /
    ``False`` / empty string on any exception so the orchestrator pipeline
    never stalls because the chassis endpoint happened to be down.
  * All 3 methods share a single httpx ``AsyncClient`` instance that lives
    on this bridge (lazily constructed, no global state).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .client import (
    A2AAgentCard,
    A2AClient,
    A2AMessage,
    A2ATask,
    A2ATaskState,
    create_agent_card,
)

_log = logging.getLogger(__name__)

# HTTP round-trip timeout for the ping/echo handshake.  Anything slower means
# the sidecar isn't there and we must NOT block mainline work.
_HANDSHAKE_TIMEOUT_S = 5.0
_REQUEST_TIMEOUT_S = 60.0


@dataclass(slots=True)
class BridgeStatus:
    """Structured liveness result for ``/api/v1/health`` panels."""

    reachable: bool
    latency_ms: float
    endpoint: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "latency_ms": round(self.latency_ms, 2),
            "endpoint": self.endpoint,
            "error": self.error,
        }


class BaiLongmaBridge:
    """A2A client wrapper for the BaiLongma chassis sidecar.

    The bridge does *not* keep process-lifetime httpx connections to avoid
    leaking descriptors on Settings reload.  Instantiate, call, drop.
    """

    def __init__(
        self,
        *,
        endpoint: str = "",
        agent_card: A2AAgentCard | None = None,
        self_name: str = "qnm-os",
        self_url: str = "http://localhost:8011/api/v1/a2a",
    ) -> None:
        # Default endpoint is intentionally empty: callers must opt in via
        # Settings.bailongma_endpoint or the environment, so a missing chassis
        # never produces spurious connection errors.
        self._endpoint = endpoint.strip()
        self._local_card = agent_card or create_agent_card(
            name=self_name,
            description="qnm-os (MoRE OS) — layered cognition + governance",
            url=self_url,
            skills=["L0-L5 layered pipeline", "RBAC policy enforcer", "LLM fallback"],
        )
        self._a2a = A2AClient(self._local_card)

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Returns True only when a chassis endpoint was actually configured."""
        return bool(self._endpoint)

    async def ping(self) -> BridgeStatus:
        """Low-level handshake: GET /health on the chassis URL.

        Uses httpx directly (not A2A JSON-RPC) because the chassis' /health
        is the *canonical* liveness probe even before A2A is wired up.
        Returns a :class:`BridgeStatus` struct; ``reachable=False`` with a
        human-readable ``error`` on any exception.
        """
        if not self._endpoint:
            return BridgeStatus(False, 0.0, "", "endpoint not configured")
        import httpx
        import time

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=_HANDSHAKE_TIMEOUT_S) as h:
                r = await h.get(self._endpoint.rstrip("/") + "/health")
            latency_ms = (time.perf_counter() - t0) * 1000.0
            if 200 <= r.status_code < 300:
                return BridgeStatus(True, latency_ms, self._endpoint)
            return BridgeStatus(
                False, latency_ms, self._endpoint, f"HTTP {r.status_code}"
            )
        except Exception as exc:  # pragma: no cover - defensive
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return BridgeStatus(False, latency_ms, self._endpoint, repr(exc))

    async def echo(self, text: str = "hello-qnm") -> str:
        """JSON-RPC round-trip sanity check.

        Sends an A2A task with a single user-message containing ``text``.
        The chassis is expected to echo it back on the first message of
        the result.  Returns the echoed string or ``""`` on any failure.
        """
        if not self._endpoint:
            return ""
        try:
            task = A2ATask(
                state=A2ATaskState.SUBMITTED,
                messages=[
                    A2AMessage(
                        role="user",
                        content={"text": text, "_qnm_echo": True},
                        metadata={"mode": "echo"},
                    )
                ],
                metadata={"qnm_origin": "bailongma_bridge_v1"},
            )
            submitted = await self._post("tasks/send", task=task)
            task_id = submitted.get("taskId") or task.id
            # Attempt an immediate fetch; many echo implementations answer
            # synchronously in the /tasks/send response already.
            fetched = submitted.get("messages") or []
            if fetched:
                first = fetched[0]
                parts = first.get("parts") or []
                if parts:
                    return str(parts[0].get("text", ""))
            # Fall back to a single /tasks/get.  We do NOT poll here — if
            # the chassis needs more than one round trip, that's the
            # delegate_task caller's responsibility.
            got = await self._post("tasks/get", taskId=task_id)
            msgs = got.get("messages") or []
            if not msgs:
                return ""
            parts = msgs[0].get("parts") or []
            if not parts:
                return ""
            return str(parts[0].get("text", ""))
        except Exception:  # pragma: no cover - defensive
            return ""

    async def delegate_task(
        self,
        *,
        task_type: str,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> A2ATask | None:
        """Delegate a code-family task to the BaiLongma chassis.

        Returns the submitted :class:`A2ATask` (with state and id populated
        from the response) or ``None`` when the call failed / the bridge
        is disabled.  Poll for result later with :meth:`poll_task`.
        """
        if not self._endpoint:
            return None
        try:
            msg = A2AMessage(
                role="user",
                content={
                    "text": query,
                    "task_type": task_type,
                    "context": context or {},
                },
                metadata={"qnm_origin": "delegate_v1"},
            )
            task = A2ATask(
                state=A2ATaskState.SUBMITTED,
                messages=[msg],
                metadata={
                    "qnm_origin": "bailongma_bridge_v1",
                    "task_type": task_type,
                },
            )
            result = await self._post("tasks/send", task=task)
            state = A2ATaskState(result.get("status", {}).get("state", "submitted"))
            task.id = result.get("taskId", task.id)
            task.state = state
            return task
        except Exception:  # pragma: no cover - defensive
            return None

    async def poll_task(self, task_id: str) -> A2ATask | None:
        """Query the chassis for an existing delegated task's state."""
        if not self._endpoint or not task_id:
            return None
        try:
            result = await self._post("tasks/get", taskId=task_id)
            state = A2ATaskState(result.get("status", {}).get("state", "submitted"))
            messages: list[A2AMessage] = []
            for raw in result.get("messages", []):
                parts = raw.get("parts", [])
                text = parts[0].get("text", "") if parts else ""
                messages.append(
                    A2AMessage(
                        message_id=raw.get("messageId", ""),
                        role=raw.get("role", "agent"),
                        content={"text": text} if isinstance(text, str) else {"text": str(text)},
                    )
                )
            return A2ATask(id=task_id, state=state, messages=messages)
        except Exception:  # pragma: no cover - defensive
            return None

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a delegated task.  Returns True only on explicit success."""
        if not self._endpoint or not task_id:
            return False
        try:
            return bool(await self._post("tasks/cancel", taskId=task_id))
        except Exception:  # pragma: no cover - defensive
            return False

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    async def _post(self, method: str, **params: Any) -> dict[str, Any]:
        """Fire one JSON-RPC call and return the ``result`` dict.

        Raises on transport / JSON / JSON-RPC ``error`` — callers wrap.
        """
        import httpx
        import uuid

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": _a2a_serialize(params),
        }
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as h:
            r = await h.post(self._endpoint, json=payload)
            r.raise_for_status()
            body = r.json()
        if "error" in body:
            raise RuntimeError(f"A2A error {body['error'].get('code')}: {body['error'].get('message')}")
        return dict(body.get("result") or {})


# ----------------------------------------------------------------------
# Serialization helpers (keep close to client.py shape)
# ----------------------------------------------------------------------


def _a2a_serialize(params: dict[str, Any]) -> dict[str, Any]:
    """Convert ``task=A2ATask`` / ``taskId=str`` into the A2A JSON-RPC shape."""
    out: dict[str, Any] = {}
    task: A2ATask | None = params.get("task")
    if task is not None:
        msgs: list[dict[str, Any]] = []
        for m in task.messages:
            content = m.content if isinstance(m.content, dict) else {"text": str(m.content)}
            part_text = str(content.get("text", ""))
            msg: dict[str, Any] = {
                "messageId": m.message_id,
                "role": m.role,
                "content": content,
                "parts": [{"type": "text", "text": part_text}],
            }
            if m.metadata:
                msg["metadata"] = m.metadata
            msgs.append(msg)
        task_out: dict[str, Any] = {"id": task.id, "messages": msgs}
        if task.metadata:
            task_out["metadata"] = task.metadata
        out["task"] = task_out
    if "taskId" in params:
        out["taskId"] = params["taskId"]
    return out
