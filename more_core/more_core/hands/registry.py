"""Hand registry — discovers and indexes available Hands."""

from __future__ import annotations

import logging
from typing import Any

from .base import Hand, HandManifest

_log = logging.getLogger(__name__)


class HandRegistry:
    """Central registry for all available Hands (built-in + user-defined)."""

    def __init__(self) -> None:
        self._hands: dict[str, type[Hand]] = {}
        self._manifests: dict[str, HandManifest] = {}

    def register(self, hand_cls: type[Hand], manifest: HandManifest) -> None:
        """Register a Hand class with its manifest."""
        self._hands[manifest.id] = hand_cls
        self._manifests[manifest.id] = manifest
        _log.info("Registered Hand: %s (%s)", manifest.id, manifest.name)

    def unregister(self, hand_id: str) -> None:
        self._hands.pop(hand_id, None)
        self._manifests.pop(hand_id, None)

    def get_class(self, hand_id: str) -> type[Hand] | None:
        return self._hands.get(hand_id)

    def get_manifest(self, hand_id: str) -> HandManifest | None:
        return self._manifests.get(hand_id)

    def list_manifests(self) -> list[HandManifest]:
        return list(self._manifests.values())

    def list_ids(self) -> list[str]:
        return list(self._hands.keys())

    def stats(self) -> dict[str, Any]:
        by_cat: dict[str, int] = {}
        for m in self._manifests.values():
            by_cat[m.category] = by_cat.get(m.category, 0) + 1
        return {
            "total_hands": len(self._hands),
            "by_category": by_cat,
        }
