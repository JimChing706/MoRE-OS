"""Hand base types — autonomous agent packages.

Reference: OpenFang HAND.toml + system prompt architecture.
Adapted for Python + MoRE OS six-layer pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_log = logging.getLogger(__name__)


class HandStatus(Enum):
    """Lifecycle status of a Hand."""

    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DEACTIVATING = "deactivating"


@dataclass
class HandManifest:
    """Declarative manifest for a Hand (analogous to HAND.toml)."""

    id: str
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    category: str = "general"
    # Tools this Hand is allowed to use
    tools: list[str] = field(default_factory=list)
    # Cron schedule for autonomous operation (empty = manual only)
    schedule: str = ""
    # System prompt phases
    system_prompt: str = ""
    # Skill references injected at runtime
    skills: list[str] = field(default_factory=list)
    # Guardrail settings
    require_approval: bool = False
    approval_actions: list[str] = field(default_factory=list)
    # Resource limits
    max_tokens_per_run: int = 8192
    timeout_s: int = 300
    # Dashboard metrics to expose
    dashboard_metrics: list[str] = field(default_factory=list)
    # Configuration schema
    config_schema: dict[str, Any] = field(default_factory=dict)
    # ── v3.0 SOUL personality profile (optional) ─────────────────────
    # When set, Meta-Orchestrator weights personality matching alongside
    # capability matching when routing tasks to Experts.
    soul_profile: Any | None = None  # SoulProfile from v3.soul_profile


@dataclass
class HandResult:
    """Result of a Hand execution cycle."""

    hand_id: str
    success: bool
    output: Any = None
    error: str | None = None
    tokens_used: int = 0
    duration_ms: float = 0
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class Hand(ABC):
    """Base class for autonomous Hands.

    Subclass and implement ``execute()`` to create a custom Hand.
    The Hand manager will call ``activate()``, run on schedule, and
    ``deactivate()`` during lifecycle management.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._status = HandStatus.INACTIVE
        self._run_count = 0
        self._last_run: float | None = None
        self._total_tokens = 0
        self._errors: list[str] = []

    @property
    @abstractmethod
    def manifest(self) -> HandManifest:
        """Return the Hand manifest."""
        ...

    @property
    def status(self) -> HandStatus:
        return self._status

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "id": self.manifest.id,
            "name": self.manifest.name,
            "status": self._status.value,
            "run_count": self._run_count,
            "last_run": self._last_run,
            "total_tokens": self._total_tokens,
            "error_count": len(self._errors),
        }

    async def activate(self) -> None:
        """Activate the Hand (start autonomous operation)."""
        self._status = HandStatus.ACTIVATING
        try:
            await self.on_activate()
            self._status = HandStatus.ACTIVE
            _log.info("Hand %s activated", self.manifest.id)
        except Exception as exc:
            self._status = HandStatus.ERROR
            self._errors.append(str(exc))
            _log.exception("Hand %s activation failed", self.manifest.id)
            raise

    async def deactivate(self) -> None:
        """Deactivate the Hand (pause autonomous operation)."""
        self._status = HandStatus.DEACTIVATING
        try:
            await self.on_deactivate()
        finally:
            self._status = HandStatus.INACTIVE
            _log.info("Hand %s deactivated", self.manifest.id)

    async def pause(self) -> None:
        """Pause without losing state."""
        self._status = HandStatus.PAUSED
        _log.info("Hand %s paused", self.manifest.id)

    async def resume(self) -> None:
        """Resume from paused state."""
        if self._status == HandStatus.PAUSED:
            self._status = HandStatus.ACTIVE
            _log.info("Hand %s resumed", self.manifest.id)

    async def run(self, context: dict[str, Any] | None = None) -> HandResult:
        """Execute one cycle of the Hand."""
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.execute(context or {}),
                timeout=self.manifest.timeout_s,
            )
            self._run_count += 1
            self._last_run = time.time()
            self._total_tokens += result.tokens_used
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except asyncio.TimeoutError:
            return HandResult(
                hand_id=self.manifest.id,
                success=False,
                error=f"timeout after {self.manifest.timeout_s}s",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            self._errors.append(str(exc))
            return HandResult(
                hand_id=self.manifest.id,
                success=False,
                error=str(exc),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    # -- hooks for subclasses -----------------------------------------------

    async def on_activate(self) -> None:
        """Override to perform setup on activation."""
        pass

    async def on_deactivate(self) -> None:
        """Override to perform cleanup on deactivation."""
        pass

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> HandResult:
        """Execute one autonomous cycle. Must be implemented by subclass."""
        ...
