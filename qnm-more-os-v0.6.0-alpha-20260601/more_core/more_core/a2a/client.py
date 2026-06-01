"""A2A Protocol - Agent-to-Agent Communication.

Reference: Google A2A Protocol (https://a2aprotocol.github.io)
设计: 代理间任务分发、结果返回、心跳保持
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


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
    content: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class A2ATask:
    """A2A task."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: A2ATaskState = A2ATaskState.SUBMITTED
    messages: list[A2AMessage] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class A2AAgentCard:
    """A2A Agent Card - 代理能力描述."""
    name: str
    description: str
    url: str
    version: str = "1.0"
    capabilities: dict = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    authentication: dict = field(default_factory=dict)
    provider: dict = field(default_factory=dict)


class A2AClient:
    """A2A Client - 与其他代理通信."""
    
    def __init__(self, agent_card: A2AAgentCard):
        self._agent_card = agent_card
        self._session: dict[str, Any] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._handlers: dict[str, Callable] = {}
    
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
    
    def register_handler(self, method: str, handler: Callable) -> None:
        """注册消息处理 handler."""
        self._handlers[method] = handler
    
    async def handle_message(self, message: A2AMessage) -> A2AMessage | None:
        """处理接收到的消息."""
        handler = self._handlers.get(message.content.get("method"))
        if handler:
            return await handler(message)
        return None
    
    def get_agent_card(self) -> A2AAgentCard:
        """获取代理卡片."""
        return self._agent_card


class A2AServer:
    """A2A Server - 接收和处理来自其他代理的请求."""
    
    def __init__(self, agent_card: A2AAgentCard):
        self._agent_card = agent_card
        self._tasks: dict[str, A2ATask] = {}
        self._task_handler: Callable | None = None
    
    def set_task_handler(self, handler: Callable[[A2ATask], Awaitable[A2ATask]]) -> None:
        """设置任务处理函数."""
        self._task_handler = handler
    
    async def handle_request(self, request: dict) -> dict:
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
        else:
            return {"error": {"code": -32601, "message": f"Method not found: {method}"}}
    
    async def _handle_send_task(self, params: dict) -> dict:
        """处理任务发送."""
        task_data = params.get("task", {})
        task = A2ATask(
            id=task_data.get("id", str(uuid.uuid4())),
            state=A2ATaskState.WORKING,
        )
        
        for msg_data in task_data.get("messages", []):
            message = A2AMessage(
                message_id=msg_data.get("messageId", str(uuid.uuid4())),
                role=msg_data.get("role", "user"),
                content={"text": msg_data.get("parts", [{}])[0].get("text", "")},
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
    
    async def _handle_get_task(self, params: dict) -> dict:
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
    
    async def _handle_cancel_task(self, params: dict) -> dict:
        """处理任务取消."""
        task_id = params.get("taskId", "")
        if task_id in self._tasks:
            self._tasks[task_id].state = A2ATaskState.CANCELED
            return {"jsonrpc": "2.0", "id": "", "result": {"taskId": task_id}}
        return {"error": {"code": -32602, "message": "Task not found"}}
    
    def _handle_get_card(self) -> dict:
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