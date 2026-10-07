"""Hand manager — lifecycle, scheduling, and execution of autonomous Hands."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..core.errors import PluginError
from ..security.rbac import Permission, get_rbac
from .base import Hand, HandResult, HandStatus
from .registry import HandRegistry

if TYPE_CHECKING:
    from ..cron.scheduler import CronScheduler

_log = logging.getLogger(__name__)


class HandManager:
    """Manages the lifecycle of active Hands.

    Integrates with CronScheduler for autonomous scheduled execution,
    and exposes API-friendly status/control methods.
    """

    def __init__(
        self,
        registry: HandRegistry,
        scheduler: CronScheduler | None = None,
    ) -> None:
        self._registry = registry
        self._scheduler = scheduler
        self._active: dict[str, Hand] = {}
        self._results: dict[str, list[HandResult]] = {}

    @property
    def registry(self) -> HandRegistry:
        return self._registry

    # -- lifecycle ---------------------------------------------------------

    async def activate(self, hand_id: str, config: dict[str, Any] | None = None) -> Hand:
        """Activate a registered Hand."""
        if hand_id in self._active:
            raise PluginError(f"Hand {hand_id} is already active")

        hand_cls = self._registry.get_class(hand_id)
        if hand_cls is None:
            raise PluginError(f"Unknown Hand: {hand_id}")

        rbac = get_rbac()
        if rbac is not None:
            rbac.check_raise(
                config.get("_user_id", "anonymous") if config else "anonymous",
                Permission.HAND_ACTIVATE,
            )

        hand = hand_cls(config)
        await hand.activate()
        self._active[hand_id] = hand
        self._results.setdefault(hand_id, [])

        # Auto-schedule if the Hand has a cron expression
        if hand.manifest.schedule and self._scheduler:
            self._scheduler.add_job(
                job_id=f"hand:{hand_id}",
                name=f"Hand: {hand.manifest.name}",
                schedule=hand.manifest.schedule,
                handler=self._cron_handler(hand_id),
                timeout_s=hand.manifest.timeout_s,
                description=f"Autonomous Hand: {hand.manifest.description}",
            )

        return hand

    async def deactivate(self, hand_id: str) -> None:
        """Deactivate a running Hand."""
        hand = self._active.pop(hand_id, None)

        rbac = get_rbac()
        if rbac is not None:
            rbac.check_raise("anonymous", Permission.HAND_DEACTIVATE)

        if hand is None:
            return
        # Remove cron job
        if self._scheduler:
            self._scheduler.remove_job(f"hand:{hand_id}")
        await hand.deactivate()

    async def pause(self, hand_id: str) -> None:
        hand = self._active.get(hand_id)
        if hand:
            await hand.pause()

    async def resume(self, hand_id: str) -> None:
        hand = self._active.get(hand_id)
        if hand:
            await hand.resume()

    async def run_once(self, hand_id: str, context: dict[str, Any] | None = None) -> HandResult:
        """Manually trigger one execution cycle."""

        rbac = get_rbac()
        if rbac is not None:
            rbac.check_raise(
                context.get("_user_id", "anonymous") if context else "anonymous",
                Permission.HAND_RUN,
            )

        hand = self._active.get(hand_id)
        if hand is None:
            return HandResult(hand_id=hand_id, success=False, error="Hand not active")
        result = await hand.run(context)
        self._results[hand_id].append(result)
        # Trim history
        if len(self._results[hand_id]) > 100:
            self._results[hand_id] = self._results[hand_id][-100:]
        return result

    # -- queries -----------------------------------------------------------

    def get_hand(self, hand_id: str) -> Hand | None:
        return self._active.get(hand_id)

    def list_active(self) -> list[dict[str, Any]]:
        return [hand.stats for hand in self._active.values()]

    def get_results(self, hand_id: str, limit: int = 10) -> list[HandResult]:
        return self._results.get(hand_id, [])[-limit:]

    def status(self, hand_id: str) -> HandStatus | None:
        hand = self._active.get(hand_id)
        return hand.status if hand else None

    def stats(self) -> dict[str, Any]:
        return {
            "total_registered": len(self._registry.list_ids()),
            "total_active": len(self._active),
            "active_hands": [h.stats for h in self._active.values()],
            "registry": self._registry.stats(),
        }

    # -- shutdown ----------------------------------------------------------

    async def stop_all(self) -> None:
        for hand_id in list(self._active.keys()):
            try:
                await self.deactivate(hand_id)
            except Exception:  # noqa: BLE001
                _log.exception("Failed to deactivate hand %s", hand_id)

    # -- internal ----------------------------------------------------------

    def _cron_handler(self, hand_id: str) -> Callable[..., Awaitable[Any]]:
        async def _handler(**kwargs: Any) -> Any:
            result = await self.run_once(hand_id)
            return result.output

        return _handler
