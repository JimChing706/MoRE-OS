"""Health & System state router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Health & System"])

    deps = [Depends(require_api_key)] if require_api_key else []

    @router.get("/health", dependencies=deps)
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "version": core.settings.version if hasattr(core.settings, "version") else "0.5.0",
            "gates": {
                "symbolic": core.settings.enable_symbolic,
                "evolution": core.settings.enable_evolution,
                "metacognition": core.settings.enable_metacognition,
            },
            "llm_providers": core.llm.list_providers(),
        }

    @router.get("/system/state", dependencies=deps)
    async def system_state() -> dict[str, Any]:
        metrics_snap = core._metrics.snapshot()
        total = metrics_snap.total_requests
        error_rate = metrics_snap.failure_count / total if total > 0 else 0.0
        return {
            "status": "running",
            "active_layers": ["L0", "L1", "L2", "L3", "L4", "L5"],
            "throughput": total,
            "avg_latency": metrics_snap.avg_duration_ms,
            "error_rate": error_rate,
            "active_tasks": 0,
            "queued_tasks": 0,
            "registry": core.registry.stats(),
            "evolution": core.evolution_archive.stats(),
            "memory": {
                "stats": core.memory.stats(),
                "entries": [
                    {"id": e.id, "type": e.kind.value, "content": e.content,
                     "tags": e.tags, "score": e.score, "timestamp": e.created_at,
                     "access_count": e.access_count}
                    for e in core.memory.list()
                ],
            },
            "active_plugins": [md.name for md in core.plugins.active()],
        }

    return router
