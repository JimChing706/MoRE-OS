"""Deployment Manager — lifecycle management for agents and services.

Manages deployment slots where Hands, Skills, and Workflows run.
Provides health monitoring, auto-restart, and scaling controls.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class DeploymentStatus(Enum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


class DeploymentType(Enum):
    HAND = "hand"
    SKILL = "skill"
    WORKFLOW = "workflow"
    SERVICE = "service"


@dataclass
class HealthCheck:
    """Health check result for a deployment."""

    healthy: bool = True
    last_check: float = 0
    consecutive_failures: int = 0
    message: str = ""


@dataclass
class Deployment:
    """A deployment slot tracking an active agent/service."""

    id: str
    name: str
    type: DeploymentType
    target_id: str  # Hand ID, Skill ID, or Workflow ID
    status: DeploymentStatus = DeploymentStatus.PENDING
    config: dict[str, Any] = field(default_factory=dict)
    health: HealthCheck = field(default_factory=HealthCheck)
    # Lifecycle
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    stopped_at: float | None = None
    restart_count: int = 0
    # Limits
    max_restarts: int = 5
    health_interval_s: float = 30.0
    auto_restart: bool = True
    # Metadata
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def uptime_s(self) -> float:
        if self.started_at and self.status == DeploymentStatus.RUNNING:
            return time.time() - self.started_at
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "target_id": self.target_id,
            "status": self.status.value,
            "health": {
                "healthy": self.health.healthy,
                "last_check": self.health.last_check,
                "consecutive_failures": self.health.consecutive_failures,
                "message": self.health.message,
            },
            "uptime_s": round(self.uptime_s, 1),
            "restart_count": self.restart_count,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "labels": self.labels,
        }


class DeploymentManager:
    """Manages all active deployments with health monitoring."""

    def __init__(self) -> None:
        self._deployments: dict[str, Deployment] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._running = False
        self._deploy_handlers: dict[DeploymentType, Any] = {}
        self._undeploy_handlers: dict[DeploymentType, Any] = {}

    def set_handler(
        self,
        dtype: DeploymentType,
        deploy_fn: Any,
        undeploy_fn: Any,
    ) -> None:
        """Register deploy/undeploy handlers for a deployment type."""
        self._deploy_handlers[dtype] = deploy_fn
        self._undeploy_handlers[dtype] = undeploy_fn

    # -- lifecycle --

    async def deploy(
        self,
        name: str,
        dtype: DeploymentType,
        target_id: str,
        config: dict[str, Any] | None = None,
        labels: dict[str, str] | None = None,
        auto_restart: bool = True,
    ) -> Deployment:
        """Create and start a new deployment."""
        dep_id = f"dep_{uuid.uuid4().hex[:8]}"
        dep = Deployment(
            id=dep_id,
            name=name,
            type=dtype,
            target_id=target_id,
            config=config or {},
            labels=labels or {},
            auto_restart=auto_restart,
        )
        self._deployments[dep_id] = dep

        dep.status = DeploymentStatus.DEPLOYING
        try:
            handler = self._deploy_handlers.get(dtype)
            if handler:
                await handler(target_id, config or {})
            dep.status = DeploymentStatus.RUNNING
            dep.started_at = time.time()
            dep.health.healthy = True
            dep.health.last_check = time.time()
            _log.info("Deployed %s: %s (%s)", dtype.value, name, dep_id)
        except Exception as exc:  # noqa: BLE001
            dep.status = DeploymentStatus.FAILED
            dep.health.healthy = False
            dep.health.message = str(exc)
            _log.error("Deploy failed %s: %s", name, exc)

        return dep

    async def undeploy(self, dep_id: str) -> bool:
        """Stop and remove a deployment."""
        dep = self._deployments.get(dep_id)
        if dep is None:
            return False

        try:
            handler = self._undeploy_handlers.get(dep.type)
            if handler:
                await handler(dep.target_id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("Undeploy handler error: %s", exc)

        dep.status = DeploymentStatus.STOPPED
        dep.stopped_at = time.time()
        _log.info("Undeployed: %s (%s)", dep.name, dep_id)
        return True

    async def restart(self, dep_id: str) -> bool:
        """Restart a deployment."""
        dep = self._deployments.get(dep_id)
        if dep is None:
            return False

        dep.status = DeploymentStatus.RESTARTING
        dep.restart_count += 1

        try:
            handler_stop = self._undeploy_handlers.get(dep.type)
            if handler_stop:
                await handler_stop(dep.target_id)

            handler_start = self._deploy_handlers.get(dep.type)
            if handler_start:
                await handler_start(dep.target_id, dep.config)

            dep.status = DeploymentStatus.RUNNING
            dep.started_at = time.time()
            dep.health.healthy = True
            dep.health.consecutive_failures = 0
            return True
        except Exception as exc:  # noqa: BLE001
            dep.status = DeploymentStatus.FAILED
            dep.health.message = str(exc)
            return False

    async def remove(self, dep_id: str) -> bool:
        """Undeploy and remove from registry."""
        await self.undeploy(dep_id)
        return self._deployments.pop(dep_id, None) is not None

    # -- health monitoring --

    async def start_health_monitor(self) -> None:
        self._running = True
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop_health_monitor(self) -> None:
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None

    async def _health_loop(self) -> None:
        while self._running:
            for dep in list(self._deployments.values()):
                if dep.status != DeploymentStatus.RUNNING:
                    continue
                # Simple liveness check
                dep.health.last_check = time.time()
                # Auto-restart on repeated failures
                if (
                    not dep.health.healthy
                    and dep.auto_restart
                    and dep.restart_count < dep.max_restarts
                ):
                    _log.warning(
                        "Auto-restarting %s (failures=%d)",
                        dep.name,
                        dep.health.consecutive_failures,
                    )
                    await self.restart(dep.id)
            await asyncio.sleep(10)

    def mark_unhealthy(self, dep_id: str, message: str = "") -> None:
        dep = self._deployments.get(dep_id)
        if dep:
            dep.health.healthy = False
            dep.health.consecutive_failures += 1
            dep.health.message = message

    def mark_healthy(self, dep_id: str) -> None:
        dep = self._deployments.get(dep_id)
        if dep:
            dep.health.healthy = True
            dep.health.consecutive_failures = 0
            dep.health.message = ""

    # -- queries --

    def get(self, dep_id: str) -> Deployment | None:
        return self._deployments.get(dep_id)

    def list_deployments(
        self,
        dtype: DeploymentType | None = None,
        status: DeploymentStatus | None = None,
    ) -> list[dict[str, Any]]:
        deps = list(self._deployments.values())
        if dtype:
            deps = [d for d in deps if d.type == dtype]
        if status:
            deps = [d for d in deps if d.status == status]
        return [d.to_dict() for d in deps]

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for d in self._deployments.values():
            by_status[d.status.value] = by_status.get(d.status.value, 0) + 1
            by_type[d.type.value] = by_type.get(d.type.value, 0) + 1
        healthy = sum(
            1
            for d in self._deployments.values()
            if d.health.healthy and d.status == DeploymentStatus.RUNNING
        )
        total_running = sum(
            1 for d in self._deployments.values() if d.status == DeploymentStatus.RUNNING
        )
        return {
            "total": len(self._deployments),
            "running": total_running,
            "healthy": healthy,
            "by_status": by_status,
            "by_type": by_type,
        }
