"""Incident Response System - Security and Evolution Safety."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .core.types import LayerId


class Severity(Enum):
    """Incident severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentType(Enum):
    """Types of security/evolution incidents."""

    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SELF_MODIFICATION = "self_modification"
    DGM_VARIANT_REJECTED = "dgm_variant_rejected"
    ONTOLOGY_VIOLATION = "ontology_violation"
    SANDBOX_ESCAPE = "sandbox_escape"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


class ResponseAction(Enum):
    """Incident response actions."""

    QUARANTINE = "quarantine"
    BLOCK = "block"
    AUDIT = "audit"
    ESCALATE = "escalate"
    LOG = "log"
    ROLLBACK = "rollback"


@dataclass
class Incident:
    """Represents a security or evolution incident."""

    id: str
    incident_type: IncidentType
    severity: Severity
    layer: LayerId
    timestamp: float
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    actions_taken: list[ResponseAction] = field(default_factory=list)
    resolved: bool = False
    resolution: str = ""


@dataclass
class IncidentReport:
    """Detailed incident report."""

    incident_id: str
    root_cause: str
    impact: str
    remediation: str
    prevention: list[str]
    timestamp: float


class IncidentManager:
    """Manages incident detection, response, and tracking."""

    def __init__(self, max_history: int = 1000):
        self._log = logging.getLogger(__name__)
        self._incidents: deque[Incident] = deque(maxlen=max_history)
        self._quarantined_variants: set[str] = set()
        self._blocked_actors: set[str] = set()
        self._escalation_callbacks: list[Callable[..., Any]] = []
        self._lock = asyncio.Lock()

    def register_escalation_callback(self, callback: Callable[..., Any]) -> None:
        """Register a callback for incident escalation.

        Args:
            callback: Async function to call when escalation is needed
        """
        self._escalation_callbacks.append(callback)

    async def report_incident(
        self,
        incident_type: IncidentType,
        severity: Severity,
        layer: LayerId,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> Incident:
        """Report a new incident and trigger appropriate response.

        Args:
            incident_type: Type of incident (unauthorized_access, dgm_variant_rejected, etc.)
            severity: Incident severity level
            layer: Layer where incident occurred
            description: Human-readable description
            context: Additional context data

        Returns:
            Created Incident object
        """
        incident_id = f"{incident_type.value}_{int(time.time() * 1000)}"
        incident = Incident(
            id=incident_id,
            incident_type=incident_type,
            severity=severity,
            layer=layer,
            timestamp=time.time(),
            description=description,
            context=context or {},
        )

        async with self._lock:
            self._incidents.append(incident)

        self._log.warning(
            "INCIDENT: %s [%s] %s at %s - %s",
            severity.value.upper(),
            layer.value,
            incident_type.value,
            time.strftime("%H:%M:%S", time.localtime(incident.timestamp)),
            description,
        )

        if severity in (Severity.HIGH, Severity.CRITICAL):
            await self._escalate(incident)

        return incident

    async def _escalate(self, incident: Incident) -> None:
        for callback in self._escalation_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(incident)
                else:
                    callback(incident)
            except Exception as e:  # noqa: BLE001
                self._log.error("Escalation callback failed: %s", e)

    async def handle_unauthorized_access(
        self,
        layer: LayerId,
        actor: str,
        attempted_action: str,
        context: dict[str, Any] | None = None,
    ) -> Incident:
        self._blocked_actors.add(actor)

        return await self.report_incident(
            incident_type=IncidentType.UNAUTHORIZED_ACCESS,
            severity=Severity.CRITICAL,
            layer=layer,
            description=f"Unauthorized access attempt by {actor}: {attempted_action}",
            context={
                "actor": actor,
                "action": attempted_action,
                "blocked": True,
                **(context or {}),
            },
        )

    async def handle_dgm_variant_rejected(
        self,
        variant_id: str,
        reason: str,
        verification_output: dict[str, Any] | None = None,
    ) -> Incident:
        self._quarantined_variants.add(variant_id)

        return await self.report_incident(
            incident_type=IncidentType.SELF_MODIFICATION,
            severity=Severity.HIGH,
            layer=LayerId.L2,
            description=f"DGM variant {variant_id} rejected: {reason}",
            context={
                "variant_id": variant_id,
                "reason": reason,
                "quarantined": True,
                "verification": verification_output,
            },
        )

    async def resolve_incident(self, incident_id: str, resolution: str) -> bool:
        async with self._lock:
            for incident in self._incidents:
                if incident.id == incident_id:
                    incident.resolved = True
                    incident.resolution = resolution

                    if "variant_id" in incident.context:
                        self._quarantined_variants.discard(incident.context["variant_id"])
                    if "actor" in incident.context:
                        self._blocked_actors.discard(incident.context["actor"])

                    self._log.info("Incident %s resolved: %s", incident_id, resolution)
                    return True
        return False

    def get_active_incidents(self, severity: Severity | None = None) -> list[Incident]:
        result = []
        for inc in self._incidents:
            if not inc.resolved and (severity is None or inc.severity == severity):
                result.append(inc)
        return sorted(result, key=lambda x: x.timestamp, reverse=True)

    def is_variant_quarantined(self, variant_id: str) -> bool:
        return variant_id in self._quarantined_variants

    def is_actor_blocked(self, actor: str) -> bool:
        return actor in self._blocked_actors

    def get_incident_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "total": len(self._incidents),
            "active": sum(1 for i in self._incidents if not i.resolved),
            "by_severity": {s.value: 0 for s in Severity},
            "by_type": {t.value: 0 for t in IncidentType},
            "by_layer": {},
        }
        for inc in self._incidents:
            if not inc.resolved:
                stats["by_severity"][inc.severity.value] += 1
                stats["by_type"][inc.incident_type.value] += 1
                layer_key = inc.layer.value
                stats["by_layer"][layer_key] = stats["by_layer"].get(layer_key, 0) + 1
        return stats


_global_incident_manager = IncidentManager()


def get_incident_manager() -> IncidentManager:
    return _global_incident_manager
