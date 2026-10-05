"""Monitor router — dashboard snapshot, full health, WebSocket."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ...runtime.orchestrator import MoRECore


def create_router(core: MoRECore, require_api_key: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    deps = [Depends(require_api_key)] if require_api_key else []

    @router.get("/monitor/dashboard", dependencies=deps)
    async def dashboard_snapshot() -> dict[str, Any]:
        from ..monitor import build_dashboard_snapshot

        return build_dashboard_snapshot(core)

    @router.get("/monitor/health", dependencies=deps)
    async def full_health() -> dict[str, Any]:
        import time as _time

        return {
            "status": "healthy",
            "uptime_s": round(_time.time() - core._start_time, 1),
            "subsystems": {
                "hands": {
                    "registered": len(core.hand_registry.list_ids()),
                    "active": len(core.hands.list_active()),
                },
                "skills": core.skill_manager.get_stats(),
                "workflows": core.workflows.stats(),
                "deployments": core.deployment_manager.stats(),
                "schedules": {"jobs": len(core.cron.list_jobs())},
                "channels": {
                    "count": len(core.channels.list_channels()),
                    "running": core.channels.is_running(),
                },
                "llm": {
                    "providers": len(core.llm.list_providers()),
                    "aliases": core.model_aliases.stats()["total_aliases"]
                    if core.model_aliases
                    else 0,
                },
                "security": {
                    "rbac": core.rbac.enabled,
                    "output_rules": core.output_filter.stats()["enabled_rules"],
                },
                "sessions": core.session_manager.stats(),
            },
        }

    @router.get("/metrics/llm", dependencies=deps)
    async def llm_metrics(window_s: int = 3600) -> dict[str, Any]:
        """Core runtime metrics: tokens, latency percentiles, success rate.

        This is the canonical observability surface for "how much did the
        platform actually do, and how fast" — it reads the ``llm_calls``
        telemetry table written by ``governance.observability``.
        """
        from ...governance import observability as _obs

        return {"status": "ok", "window_s": int(window_s), "metrics": _obs.summary(window_s)}

    @router.get("/metrics/llm/recent", dependencies=deps)
    async def llm_metrics_recent(limit: int = 50) -> dict[str, Any]:
        """Recent raw LLM call rows (provider/model/latency/tokens/success)."""
        from ...governance import observability as _obs

        rows = _obs.query_recent_llm(limit=max(1, min(int(limit), 500)))
        return {"status": "ok", "count": len(rows), "calls": rows}

    @router.get("/metrics/governance", dependencies=deps)
    async def governance_metrics(window_s: int = 3600) -> dict[str, Any]:
        """治理拦截率指标 + 阈值告警（对应"可观测性"硬伤）。

        读取 ``governance_events`` 遥测表（每次 L3 治理评估一行，通过/拦截
        均记录），返回自洽的拦截率与按规则的命中分布，并在读取时求值
        阈值告警（纯函数，无副作用）。
        """
        from ...governance import observability as _obs

        stats = _obs.query_governance_stats(window_s)
        return {
            "status": "ok",
            "window_s": int(window_s),
            "metrics": stats,
            "alerts": _obs.evaluate_governance_alerts(stats),
        }

    @router.get("/metrics/governance/prometheus", include_in_schema=False)
    async def governance_prometheus(window_s: int = 3600) -> Any:
        """治理指标的 Prometheus 文本导出（供 scrape / Grafana 直接消费）。"""
        from fastapi.responses import PlainTextResponse

        from ...governance import observability as _obs

        st = _obs.query_governance_stats(window_s)
        alerts = _obs.evaluate_governance_alerts(st)
        lines = [
            "# HELP more_os_governance_requests Governance-evaluated requests in window.",
            "# TYPE more_os_governance_requests gauge",
            f"more_os_governance_requests {int(st.get('requests') or 0)}",
            "# HELP more_os_governance_blocked_requests Requests blocked by governance.",
            "# TYPE more_os_governance_blocked_requests gauge",
            f"more_os_governance_blocked_requests {int(st.get('blocked_requests') or 0)}",
            "# HELP more_os_governance_blocked_rate Blocked requests / evaluated requests.",
            "# TYPE more_os_governance_blocked_rate gauge",
            f"more_os_governance_blocked_rate {float(st.get('blocked_rate') or 0.0)}",
            "# HELP more_os_governance_destructive_blocks Destructive requests blocked.",
            "# TYPE more_os_governance_destructive_blocks gauge",
            f"more_os_governance_destructive_blocks {int(st.get('destructive_blocks') or 0)}",
        ]
        lines.append("# TYPE more_os_governance_rule_hits_total gauge")
        for rule, hits in (st.get("by_rule") or {}).items():
            safe = str(rule).replace('"', "")
            lines.append(f'more_os_governance_rule_hits_total{{rule="{safe}"}} {int(hits)}')
        lines.append("# TYPE more_os_governance_alerts gauge")
        for a in alerts:
            code = str(a.get("code", "")).replace('"', "")
            lvl = str(a.get("level", "")).replace('"', "")
            lines.append(f'more_os_governance_alerts{{level="{lvl}",code="{code}"}} 1')
        return PlainTextResponse("\n".join(lines) + "\n")

    @router.get("/metrics/dashboard", include_in_schema=False)
    async def metrics_dashboard() -> Any:
        """自托管实时指标看板（无密钥内嵌；页面内输入 API Key 后轮询）。"""
        from fastapi.responses import HTMLResponse

        from ..metrics_dashboard import DASHBOARD_HTML

        return HTMLResponse(DASHBOARD_HTML)

    @router.websocket("/monitor")
    async def ws_monitor(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time dashboard updates."""
        expected = os.getenv("MORE_API_KEY", "")
        if expected:
            token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not token or token != expected:
                await websocket.close(code=4001)
                return
        await websocket.accept()
        import asyncio as _aio
        from ..monitor import build_dashboard_snapshot

        try:
            await websocket.send_json({"event": "snapshot", "data": build_dashboard_snapshot(core)})
            while True:
                await _aio.sleep(3)
                snapshot = build_dashboard_snapshot(core)
                await websocket.send_json({"event": "update", "data": snapshot})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    return router
