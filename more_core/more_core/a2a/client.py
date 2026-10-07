"""A2A Protocol - Agent-to-Agent Communication.

Reference: Google A2A Protocol (https://a2aprotocol.github.io)
设计: 代理间任务分发、结果返回、心跳保持
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast


class A2ATaskState(Enum):
    """A2A task states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class A2AMessage:
    """A2A message envelope."""

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    agent_id: str = ""
    role: str = "user"  # user or agent
    content: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class A2ATask:
    """A2A task."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: A2ATaskState = A2ATaskState.SUBMITTED
    messages: list[A2AMessage] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class A2AAgentCard:
    """A2A Agent Card - 代理能力描述."""

    name: str
    description: str
    url: str
    version: str = "1.0"
    capabilities: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    authentication: dict[str, Any] = field(default_factory=dict)
    provider: dict[str, Any] = field(default_factory=dict)


class A2AClient:
    """A2A Client - 与其他代理通信."""

    def __init__(self, agent_card: A2AAgentCard):
        self._agent_card = agent_card
        self._session: dict[str, Any] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    async def send_task(self, target_url: str, task: A2ATask) -> A2ATask:
        """发送任务到目标代理."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/send",
            "params": {
                "task": {
                    "id": task.id,
                    "messages": [
                        {
                            "messageId": m.message_id,
                            "role": m.role,
                            "parts": [{"type": "text", "text": m.content.get("text", "")}],
                        }
                        for m in task.messages
                    ],
                },
            },
        }

        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(target_url, json=payload)
            result = r.json().get("result", {})

            task.id = result.get("taskId", task.id)
            task.state = A2ATaskState(result.get("status", {}).get("state", "submitted"))

            return task

    async def send_task_query(self, target_url: str, task_id: str) -> A2ATask:
        """查询任务状态."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"taskId": task_id},
        }

        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(target_url, json=payload)
            result = r.json().get("result", {})

            task = A2ATask(
                id=task_id,
                state=A2ATaskState(result.get("status", {}).get("state", "submitted")),
            )
            return task

    async def cancel_task(self, target_url: str, task_id: str) -> bool:
        """取消任务."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/cancel",
            "params": {"taskId": task_id},
        }

        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(target_url, json=payload)
            return r.json().get("result") is not None

    def register_handler(self, method: str, handler: Callable[..., Any]) -> None:
        """注册消息处理 handler."""
        self._handlers[method] = handler

    async def handle_message(self, message: A2AMessage) -> A2AMessage | None:
        """处理接收到的消息."""
        handler = self._handlers.get(str(message.content.get("method", "")))
        if handler:
            return cast(A2AMessage | None, await handler(message))
        return None

    def get_agent_card(self) -> A2AAgentCard:
        """获取代理卡片."""
        return self._agent_card


class A2AServer:
    """A2A Server - 接收和处理来自其他代理的请求."""

    def __init__(self, agent_card: A2AAgentCard):
        self._agent_card = agent_card
        self._tasks: dict[str, A2ATask] = {}
        self._task_handler: Callable[..., Any] | None = None

    def set_task_handler(self, handler: Callable[[A2ATask], Awaitable[A2ATask]]) -> None:
        """设置任务处理函数."""
        self._task_handler = handler

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """处理 A2A 请求."""
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "tasks/send":
            return await self._handle_send_task(params)
        elif method == "tasks/get":
            return await self._handle_get_task(params)
        elif method == "tasks/cancel":
            return await self._handle_cancel_task(params)
        elif method == "agent/card":
            return self._handle_get_card()
        elif method == "tasks/list":
            return self._handle_list_tasks(params)
        else:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}

    # -- Step-4 P2: stats / monitoring helpers for the health endpoint ---

    def stats(self) -> dict[str, Any]:
        """Return task counts by state (cheap, O(n) where n = active tasks)."""
        counts: dict[str, int] = {s.value: 0 for s in A2ATaskState}
        for task in self._tasks.values():
            counts[task.state.value] = counts.get(task.state.value, 0) + 1
        return {
            "task_count": len(self._tasks),
            "by_state": counts,
            "agent_name": self._agent_card.name,
            "agent_url": self._agent_card.url,
        }

    def _handle_list_tasks(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return a compact list of tasks (optionally filtered by state)."""
        state_filter = str(params.get("state", "")).lower() or None
        limit = int(params.get("limit", 50))
        tasks_view: list[dict[str, Any]] = []
        for task in list(self._tasks.values())[-limit:]:
            if state_filter and task.state.value != state_filter:
                continue
            tasks_view.append(
                {
                    "id": task.id,
                    "state": task.state.value,
                    "message_count": len(task.messages),
                    "metadata": task.metadata or {},
                }
            )
        return {
            "jsonrpc": "2.0",
            "id": "",
            "result": {
                "tasks": tasks_view,
                "count": len(tasks_view),
                "total": len(self._tasks),
            },
        }

    async def _handle_send_task(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理任务发送."""
        task_data = params.get("task", {})
        task = A2ATask(
            id=task_data.get("id", str(uuid.uuid4())),
            state=A2ATaskState.WORKING,
            metadata=task_data.get("metadata") or {},
        )

        for msg_data in task_data.get("messages", []):
            # Prefer body.content dict directly for BaiLongma-style messages.
            raw_content: dict[str, Any] = msg_data.get("content") or {}
            parts = msg_data.get("parts") or [{}]
            # Coerce the message-level content dict: accept either the
            # message-level ``content`` field OR (if absent) the first part's
            # text as the content.text, with ``task_type`` inherited from
            # message metadata to preserve chassis-origin fields.
            if not isinstance(raw_content, dict):
                raw_content = {"text": str(raw_content)}
            if not raw_content.get("text"):
                part_text = parts[0].get("text", "") if parts else ""
                if part_text:
                    raw_content.setdefault("text", part_text)
            # task_type/context fallbacks: message-level content → message metadata
            meta: dict[str, Any] = msg_data.get("metadata") or {}
            if not raw_content.get("task_type") and meta.get("task_type"):
                raw_content["task_type"] = meta["task_type"]
            if not raw_content.get("context") and isinstance(meta.get("context"), dict):
                raw_content["context"] = meta["context"]
            message = A2AMessage(
                message_id=msg_data.get("messageId", str(uuid.uuid4())),
                role=msg_data.get("role", "user"),
                content=raw_content,
                metadata=meta,
            )
            task.messages.append(message)

        self._tasks[task.id] = task

        if self._task_handler:
            task = await self._task_handler(task)

        return {
            "jsonrpc": "2.0",
            "id": "",
            "result": {
                "taskId": task.id,
                "status": {"state": task.state.value},
            },
        }

    async def _handle_get_task(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理任务查询."""
        task_id = params.get("taskId", "")
        task = self._tasks.get(task_id)

        if not task:
            return {"error": {"code": -32602, "message": "Task not found"}}

        return {
            "jsonrpc": "2.0",
            "id": "",
            "result": {
                "taskId": task.id,
                "status": {"state": task.state.value},
                "messages": [
                    {
                        "messageId": m.message_id,
                        "role": m.role,
                        "parts": [{"type": "text", "text": m.content.get("text", "")}],
                    }
                    for m in task.messages
                ],
            },
        }

    async def _handle_cancel_task(self, params: dict[str, Any]) -> dict[str, Any]:
        """处理任务取消."""
        task_id = params.get("taskId", "")
        if task_id in self._tasks:
            self._tasks[task_id].state = A2ATaskState.CANCELED
            return {"jsonrpc": "2.0", "id": "", "result": {"taskId": task_id}}
        return {"error": {"code": -32602, "message": "Task not found"}}

    def _handle_get_card(self) -> dict[str, Any]:
        """处理获取代理卡片."""
        return {
            "jsonrpc": "2.0",
            "id": "",
            "result": {
                "agent": {
                    "name": self._agent_card.name,
                    "description": self._agent_card.description,
                    "url": self._agent_card.url,
                    "version": self._agent_card.version,
                    "capabilities": self._agent_card.capabilities,
                    "skills": self._agent_card.skills,
                },
            },
        }


def create_agent_card(
    name: str,
    description: str,
    url: str,
    skills: list[str] | None = None,
) -> A2AAgentCard:
    """Factory function to create agent card."""
    return A2AAgentCard(
        name=name,
        description=description,
        url=url,
        skills=skills or [],
    )
