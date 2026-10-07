"""Health & System state router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Health & System"])

    deps = [Depends(require_api_key)] if require_api_key else []

    # ── Step-4 P0: observability path bootstrap ──────────────────
    # If settings carry an explicit observability SQLite path, configure
    # the module-level singleton at router-creation time so the first
    # record_* call does not have to derive a default.
    try:
        from ...governance import observability as _obs

        _settings = getattr(core, "settings", None)
        _explicit = getattr(_settings, "bailongma_observability_path", None)
        if _explicit:
            _obs.configure(str(_explicit))
    except Exception:  # pragma: no cover - defensive  # noqa: BLE001, S110
        pass

    @router.get("/health", dependencies=deps)
    async def health() -> dict[str, Any]:
        settings = getattr(core, "settings", None)

        # ── Step-4 P0: sidecar liveness ──────────────────────────
        # Ping the BaiLongma chassis if an endpoint was configured.
        sidecar: dict[str, Any] = {"configured": False}
        endpoint = getattr(settings, "bailongma_endpoint", "") if settings else ""
        if endpoint:
            try:
                from ...a2a.bailongma_bridge import BaiLongmaBridge

                bridge = BaiLongmaBridge(endpoint=endpoint)
                status = await bridge.ping()
                sidecar = status.to_dict()
                sidecar["configured"] = True
                sidecar["delegation_gate"] = bool(
                    getattr(settings, "bailongma_enable_delegation", False)
                )
            except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
                sidecar = {
                    "configured": True,
                    "reachable": False,
                    "endpoint": endpoint,
                    "error": repr(exc),
                    "latency_ms": 0.0,
                }

        # ── Step-4 P0: observability stats ────────────────────────
        obs_stats: dict[str, Any] = {}
        try:
            from ...governance import observability as _obs

            _m = _obs.summary(3600)
            obs_stats["injection_counts_1h"] = _obs.query_injection_stats(3600)
            obs_stats["recent_llm_success_rate"] = _m.get("success_rate", 0.0)
            obs_stats["recent_llm_samples"] = _m.get("samples", 0)
            obs_stats["tokens_1h"] = _m.get("tokens", {})
            obs_stats["latency_ms_1h"] = _m.get("latency_ms", {})
            if _m.get("error"):
                obs_stats["error"] = _m["error"]
        except Exception:  # pragma: no cover - defensive  # noqa: BLE001, S110
            pass

        # ── Step-4 P0: feature-flag register + current values ────
        flag_state: dict[str, Any] = {}
        reg = getattr(settings, "feature_register", None)
        if callable(reg):
            register = reg()
            for key, meta in register.items():
                current = _resolve_flag_value(key, settings)
                flag_state[key] = {
                    "name": meta.get("name", key),
                    "desc": meta.get("desc", ""),
                    "default": meta.get("default", ""),
                    "current": current,
                }

        result: dict[str, Any] = {
            "status": "healthy",
            "version": getattr(settings, "version", "unknown"),
            "gates": {
                "symbolic": getattr(settings, "enable_symbolic", None),
                "evolution": getattr(settings, "enable_evolution", None),
                "metacognition": getattr(settings, "enable_metacognition", None),
            },
            "llm_providers": core.llm.list_providers() if getattr(core, "llm", None) else [],
            "sidecar": sidecar,
            "observability": obs_stats,
            "features": flag_state,
        }
        # ── Step-4 P2: A2A reverse-server stats ────────────────────
        # Reports tasks submitted *into* qnm-os via the /api/v1/a2a JSON-RPC
        # endpoint (BaiLongma chassis → qnm-os direction).  Stats are
        # populated only when the server exists.
        srv = getattr(core, "a2a_server", None)
        if srv is not None and hasattr(srv, "stats"):
            try:
                result["reverse_a2a"] = srv.stats()
            except Exception:  # pragma: no cover - defensive  # noqa: BLE001
                result["reverse_a2a"] = {"task_count": 0, "by_state": {}}
        else:
            result["reverse_a2a"] = {"task_count": 0, "by_state": {}}
        # ── v3.0 Meta-Orchestrator status ──────────────────────────────
        if hasattr(core, "meta_orchestrator") and core.meta_orchestrator is not None:
            result["v3"] = {
                "enabled": True,
                "meta_orchestrator": core.meta_orchestrator.get_routing_config(),
            }
        else:
            result["v3"] = {"enabled": False}
        # ── Step-4 P0: task-manager kill-switch state ──────────────────
        tm = getattr(core, "task_manager", None)
        if tm is not None and hasattr(tm, "get_killswitch_state"):
            try:
                result["killswitch"] = tm.get_killswitch_state()
            except Exception:  # pragma: no cover - defensive  # noqa: BLE001, S110
                pass
        return result

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
                    {
                        "id": e.id,
                        "type": e.kind.value,
                        "content": e.content[:200],
                        "tags": e.tags,
                        "score": e.score,
                        "timestamp": e.created_at,
                        "access_count": e.access_count,
                    }
                    for e in core.memory.list(limit=50)
                ],
            },
            "active_plugins": [md.name for md in core.plugins.active()],
        }

    return router


def _resolve_flag_value(key: str, settings: Any) -> Any:
    """Resolve dotted feature-register keys into Settings attributes.

    Examples:
      ``bailongma.enable_delegation``  -> ``settings.bailongma_enable_delegation``
      ``codegen.candidates``           -> ``settings.codegen_candidates``
      ``gates.evolution``              -> ``settings.enable_evolution``
    """
    try:
        if key.startswith("bailongma."):
            tail = key.split(".", 1)[1]
            return getattr(settings, f"bailongma_{tail}", None)
        if key.startswith("codegen."):
            tail = key.split(".", 1)[1]
            return getattr(settings, f"codegen_{tail}", None)
        if key.startswith("gates."):
            tail = key.split(".", 1)[1]
            return getattr(settings, f"enable_{tail}", None)
    except Exception:  # pragma: no cover - defensive  # noqa: BLE001, S110
        pass
    return None
