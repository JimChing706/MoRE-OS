"""Hand Persistence — save/restore/clone Hand state.

Reference: OpenFang v0.6.5 Agent Wakeup + cloneAgent.
Allows Hands to persist their state to disk, be stopped and
restarted without losing context, and be cloned to run
multiple instances with different configs.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Hand
    from .manager import HandManager

_log = logging.getLogger(__name__)


@dataclass
class HandSnapshot:
    """Serializable snapshot of a Hand's state."""
    hand_id: str
    config: dict[str, Any]
    status: str
    run_count: int
    total_tokens: int
    last_run: float | None
    errors: list[str]
    custom_state: dict[str, Any] = field(default_factory=dict)
    saved_at: float = field(default_factory=time.time)
    version: str = "1.0"


class HandPersistence:
    """Manages saving and restoring Hand state.

    Snapshots are stored as JSON files in the configured directory.
    """

    def __init__(self, state_dir: str = "data/hands") -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, hand_id: str) -> Path:
        return self._dir / f"{hand_id}.state.json"

    def save(self, hand: "Hand", custom_state: dict[str, Any] | None = None) -> HandSnapshot:
        """Save a Hand's current state to disk."""
        snapshot = HandSnapshot(
            hand_id=hand.manifest.id,
            config=hand._config,
            status=hand.status.value,
            run_count=hand._run_count,
            total_tokens=hand._total_tokens,
            last_run=hand._last_run,
            errors=list(hand._errors[-10:]),  # Keep last 10
            custom_state=custom_state or {},
        )
        path = self._path(hand.manifest.id)
        path.write_text(json.dumps(asdict(snapshot), indent=2, ensure_ascii=False))
        _log.info("Saved Hand state: %s -> %s", hand.manifest.id, path)
        return snapshot

    def load(self, hand_id: str) -> HandSnapshot | None:
        """Load a Hand snapshot from disk."""
        path = self._path(hand_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return HandSnapshot(**data)
        except Exception as exc:
            _log.error("Failed to load Hand state %s: %s", hand_id, exc)
            return None

    def restore(self, hand: "Hand", snapshot: HandSnapshot) -> None:
        """Restore a Hand's state from a snapshot."""
        hand._config = snapshot.config
        hand._run_count = snapshot.run_count
        hand._total_tokens = snapshot.total_tokens
        hand._last_run = snapshot.last_run
        hand._errors = list(snapshot.errors)
        _log.info("Restored Hand state: %s (runs=%d)", hand.manifest.id, snapshot.run_count)

    def delete(self, hand_id: str) -> bool:
        """Delete saved state for a Hand."""
        path = self._path(hand_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_saved(self) -> list[str]:
        """List all Hand IDs with saved state."""
        return [
            p.stem.replace(".state", "")
            for p in self._dir.glob("*.state.json")
        ]

    def exists(self, hand_id: str) -> bool:
        return self._path(hand_id).exists()


class HandCloner:
    """Clone a Hand to create a new instance with modified config.

    Reference: OpenFang cloneAgent feature.
    """

    def __init__(self, manager: "HandManager") -> None:
        self._manager = manager

    async def clone(
        self,
        source_id: str,
        new_id: str,
        config_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Clone an active Hand into a new instance.

        Args:
            source_id: ID of the Hand to clone
            new_id: ID for the new clone
            config_overrides: Config values to override in the clone

        Returns:
            Status dict with clone info
        """
        source = self._manager.get_hand(source_id)
        if source is None:
            return {"success": False, "error": f"Source hand not active: {source_id}"}

        # Build merged config
        merged_config = dict(source._config)
        if config_overrides:
            merged_config.update(config_overrides)

        # Get the class from registry
        hand_cls = self._manager.registry.get_class(source_id)
        if hand_cls is None:
            return {"success": False, "error": f"Hand class not found: {source_id}"}

        # Register the clone with a new manifest
        from .base import HandManifest
        original_manifest = source.manifest
        clone_manifest = HandManifest(
            id=new_id,
            name=f"{original_manifest.name} (clone)",
            description=f"Clone of {source_id}: {original_manifest.description}",
            version=original_manifest.version,
            category=original_manifest.category,
            tools=list(original_manifest.tools),
            schedule=original_manifest.schedule,
            system_prompt=original_manifest.system_prompt,
            skills=list(original_manifest.skills),
            require_approval=original_manifest.require_approval,
            max_tokens_per_run=original_manifest.max_tokens_per_run,
            timeout_s=original_manifest.timeout_s,
        )

        # Register and activate clone
        self._manager.registry.register(hand_cls, clone_manifest)
        clone = await self._manager.activate(new_id, merged_config)

        return {
            "success": True,
            "clone_id": new_id,
            "source_id": source_id,
            "config": merged_config,
            "status": clone.status.value,
        }
