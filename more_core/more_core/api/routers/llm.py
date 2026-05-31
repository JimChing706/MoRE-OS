"""LLM router — health, state, providers, usage, aliases, reasoning."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["LLM"])

    @router.get("/llm/health")
    async def llm_health() -> dict[str, bool]:
        return await core.llm.health()

    @router.get("/llm/state")
    async def llm_state() -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        return mgr.to_dict()

    @router.get("/llm/state/current")
    async def llm_current_state() -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        state = mgr.get_state()
        result = {
            "provider": state.provider, "model": state.model,
            "temperature": state.temperature, "max_tokens": state.max_tokens,
            "top_p": state.top_p, "frequency_penalty": state.frequency_penalty,
            "presence_penalty": state.presence_penalty, "timeout_s": state.timeout_s,
            "retry_count": state.retry_count, "fallback_enabled": state.fallback_enabled,
            "cache_enabled": state.cache_enabled, "streaming_enabled": state.streaming_enabled,
        }
        if state.provider == "lmstudio":
            result["lmstudio"] = {
                "endpoint": state.lmstudio_endpoint,
                "context_length": state.lmstudio_context_length,
                "gpu_layers": state.lmstudio_gpu_layers,
                "threads": state.lmstudio_threads,
                "vram_fraction": state.lmstudio_vram_fraction,
            }
        return result

    @router.post("/llm/state/update", dependencies=[Depends(require_api_key)])
    async def llm_update_state(params: dict[str, Any]) -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        allowed_keys = [
            "provider", "model", "temperature", "max_tokens",
            "top_p", "frequency_penalty", "presence_penalty",
            "timeout_s", "retry_count", "fallback_enabled",
            "cache_enabled", "streaming_enabled",
            "lmstudio_endpoint", "lmstudio_context_length",
            "lmstudio_gpu_layers", "lmstudio_threads", "lmstudio_vram_fraction",
        ]
        updates = {k: v for k, v in params.items() if k in allowed_keys}
        _validators: dict[str, tuple[type, float | None, float | None]] = {
            "temperature": (float, 0.0, 2.0), "max_tokens": (int, 1, 131072),
            "top_p": (float, 0.0, 1.0), "frequency_penalty": (float, -2.0, 2.0),
            "presence_penalty": (float, -2.0, 2.0), "timeout_s": (int, 1, 600),
            "retry_count": (int, 0, 10), "lmstudio_context_length": (int, 256, 1048576),
            "lmstudio_gpu_layers": (int, -1, 256), "lmstudio_threads": (int, 0, 256),
            "lmstudio_vram_fraction": (float, 0.0, 1.0),
        }
        errors = []
        for key, val in updates.items():
            if key in _validators:
                typ, lo, hi = _validators[key]
                try:
                    val = typ(val)
                    updates[key] = val
                except (ValueError, TypeError):
                    errors.append(f"{key}: expected {typ.__name__}")
                    continue
                if lo is not None and val < lo:
                    errors.append(f"{key}: must be >= {lo}")
                if hi is not None and val > hi:
                    errors.append(f"{key}: must be <= {hi}")
            elif key == "lmstudio_endpoint":
                if not isinstance(val, str) or not val.startswith(("http://", "https://")):
                    errors.append("lmstudio_endpoint: must be a valid http(s) URL")
        if errors:
            raise HTTPException(status_code=422, detail="; ".join(errors))
        new_state = mgr.update_state(**updates)
        return {"success": True, "updated": updates, "current_state": new_state.__dict__}

    @router.post("/llm/state/reset", dependencies=[Depends(require_api_key)])
    async def llm_reset_state() -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        state = mgr.reset_state()
        return {"success": True, "reset_to": state.__dict__}

    @router.get("/llm/usage")
    async def llm_usage() -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        usage = mgr.get_usage()
        return {
            "total_requests": usage.total_requests, "total_tokens": usage.total_tokens,
            "total_cost": usage.total_cost, "provider_usage": usage.provider_usage,
            "avg_latency_ms": usage.avg_latency_ms,
        }

    @router.get("/llm/providers")
    async def llm_providers() -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        return {"providers": mgr.get_providers_info()}

    @router.get("/llm/history")
    async def llm_history(limit: int = 10) -> dict[str, Any]:
        from ...llm.state_manager import get_llm_state_manager
        mgr = get_llm_state_manager()
        return {"history": mgr.get_history(limit)}

    @router.get("/llm/reasoning")
    async def reasoning_status() -> dict[str, Any]:
        return core.reasoning_router.stats()

    @router.post("/llm/reasoning/config", dependencies=[Depends(require_api_key)])
    async def reasoning_update(payload: dict[str, Any]) -> dict[str, Any]:
        core.reasoning_router.update_config(**payload)
        return {"success": True, "config": core.reasoning_router.stats()["config"]}

    @router.get("/llm/reasoning/check")
    async def reasoning_check(model: str) -> dict[str, Any]:
        from ...llm.reasoning import is_reasoning_model, supports_budget_tokens, get_reasoning_params
        return {
            "model": model,
            "is_reasoning": is_reasoning_model(model),
            "supports_budget": supports_budget_tokens(model),
            "params": get_reasoning_params(model, core.reasoning_router.config),
        }

    @router.get("/llm/aliases")
    async def model_aliases(free_only: bool = False) -> list[dict[str, Any]]:
        return core.model_aliases.to_api_dict(free_only)

    @router.get("/llm/aliases/resolve/{alias}")
    async def resolve_alias(alias: str) -> dict[str, Any]:
        result = core.model_aliases.resolve(alias)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Unknown alias: {alias}")
        return {
            "alias": result.alias, "provider": result.provider,
            "model": result.model, "description": result.description, "free": result.free,
        }

    return router
