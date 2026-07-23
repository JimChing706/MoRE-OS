"""Dashboard Monitor — unified real-time status aggregator.

Provides a single endpoint that aggregates the entire system status
for dashboard rendering: agents, skills, workflows, cron, channels,
security, LLM providers, and deployments.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.orchestrator import MoRECore


def build_dashboard_snapshot(core: "MoRECore") -> dict[str, Any]:
    """Build a complete dashboard snapshot for real-time monitoring.

    This is the master endpoint for the monitoring dashboard.
    Returns everything needed to render system state in one call.
    """
    return {
        "timestamp": time.time(),
        "version": core.settings.version,
        "system": _system_section(core),
        "hands": _hands_section(core),
        "skills": _skills_section(core),
        "workflows": _workflows_section(core),
        "deployments": _deployments_section(core),
        "schedules": _schedules_section(core),
        "channels": _channels_section(core),
        "llm": _llm_section(core),
        "security": _security_section(core),
        "sessions": _sessions_section(core),
    }


def _system_section(core: "MoRECore") -> dict[str, Any]:
    return {
        "status": "running",
        "uptime_s": time.time() - getattr(core, "_start_time", time.time()),
        "plugins": len(list(core.plugins.active())),
        "tools": len(core.tools.list_tools()),
        "memory_entries": core.memory.stats(),
        "incidents": core._incident_manager.get_incident_stats(),
    }


def _hands_section(core: "MoRECore") -> dict[str, Any]:
    return {
        "registered": len(core.hand_registry.list_ids()),
        "active": len(core.hands.list_active()),
        "hands": core.hands.list_active(),
        "registry": [
            {"id": m.id, "name": m.name, "category": m.category, "schedule": m.schedule}
            for m in core.hand_registry.list_manifests()
        ],
    }


def _skills_section(core: "MoRECore") -> Any:
    return core.skill_manager.get_stats()


def _workflows_section(core: "MoRECore") -> Any:
    if hasattr(core, "workflows"):
        return core.workflows.stats()
    return {"total_workflows": 0, "total_runs": 0, "active_runs": 0}


def _deployments_section(core: "MoRECore") -> Any:
    if hasattr(core, "deployment_manager"):
        return core.deployment_manager.stats()
    return {"total": 0, "running": 0, "healthy": 0}


def _schedules_section(core: "MoRECore") -> dict[str, Any]:
    jobs = core.cron.list_jobs()
    return {
        "total_jobs": len(jobs),
        "enabled": sum(1 for j in jobs if j.enabled),
        "jobs": [
            {
                "job_id": j.job_id,
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                "run_count": j.run_count,
            }
            for j in jobs
        ],
    }


def _channels_section(core: "MoRECore") -> dict[str, Any]:
    return {
        "channels": core.channels.list_channels(),
        "running": core.channels.is_running(),
        "reconnect": core.reconnect_manager.stats(),
    }


def _llm_section(core: "MoRECore") -> dict[str, Any]:
    aliases = getattr(core, "model_aliases", None)
    return {
        "providers": core.llm.list_providers(),
        "aliases": aliases.stats()
        if aliases
        else {"total_aliases": 0, "free_models": 0, "providers": []},
        "reasoning": core.reasoning_router.stats()["config"],
    }


def _security_section(core: "MoRECore") -> dict[str, Any]:
    return {
        "rbac": core.rbac.stats(),
        "taint_tracked": core.taint_tracker.stats(),
        "output_filter": core.output_filter.stats(),
    }


def _sessions_section(core: "MoRECore") -> Any:
    if hasattr(core, "session_manager"):
        return core.session_manager.stats()
    return {"total_sessions": 0, "active_sessions": 0}
