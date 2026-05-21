"""Reference plugin: code_assistant.

Demonstrates how an *industry pack* attaches to the MoRE Core without
modifying the kernel.  The plugin subscribes to ``task.started`` events
and enriches the L0 system prompt via the scratch dict carried on
:class:`LayerContext`.  It is intentionally small: real packs extend
layers, register tools, and add memories.
"""

from __future__ import annotations

from more_core.plugins.interface import PluginContext, PluginMetadata


class Plugin:
    metadata = PluginMetadata(
        name="code_assistant",
        version="0.1.0",
        description="Minimal code-assistant industry pack.",
        capabilities=["code_generation", "code_review"],
    )

    def __init__(self) -> None:
        self._unsub = None

    async def activate(self, ctx: PluginContext) -> None:
        async def _on_task_started(event):  # type: ignore[no-untyped-def]
            payload = event.data or {}
            if payload.get("type") in {"code_generation", "code_review", "code_debugging"}:
                ctx.logger.info("code_assistant engaged for task %s", payload.get("id"))

        self._unsub = ctx.event_bus.subscribe("task.started", _on_task_started)

    async def deactivate(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def capabilities(self) -> dict[str, object]:
        return {"augments_layer": "L0", "domains": ["software_engineering"]}
