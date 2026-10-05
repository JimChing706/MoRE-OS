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

    @router.get("/metrics/overview", dependencies=deps)
    async def metrics_overview(
        window_s: int = 3600, delivery_window_s: int = 86400
    ) -> dict[str, Any]:
        """MoRE OS 运行健康总览：五类核心指标 + 统一裁决 + 合并告警。

        指标族：LLM 调用（token/延迟/成功率）、交付成功率、治理拦截率、
        Council 复评、Provider 健康。``overall`` 由合并告警的最高级别决定：
        ``critical`` → critical，``warning`` → degraded，无告警 → healthy。
        """
        import time as _time

        from ...codegen.delivery_ledger import get_default_ledger
        from ...governance import observability as _obs

        llm = _obs.summary(window_s)
        governance = _obs.query_governance_stats(window_s)
        council = _obs.query_council_stats(window_s)
        providers = _obs.query_provider_health(window_s)
        try:
            delivery = get_default_ledger().stats(delivery_window_s)
        except Exception as exc:  # pragma: no cover - ledger read must not break overview
            delivery = {"error": str(exc)}

        skill_network = _obs.query_skill_network_health(window_s)
        alerts = (
            _obs.evaluate_governance_alerts(governance)
            + _obs.evaluate_provider_alerts(providers)
            + _obs.evaluate_skill_network_alerts(skill_network)
        )
        n_crit = sum(1 for a in alerts if a.get("level") == "critical")
        n_warn = sum(1 for a in alerts if a.get("level") == "warning")
        overall = "critical" if n_crit else ("degraded" if n_warn else "healthy")

        return {
            "status": "ok",
            "generated_at": _time.time(),
            "window_s": int(window_s),
            "delivery_window_s": int(delivery_window_s),
            "overall": overall,
            "alert_counts": {"critical": n_crit, "warning": n_warn},
            "alerts": alerts,
            "llm": llm,
            "delivery": delivery,
            "governance": governance,
            "council": council,
            "skill_network": {
                "ok": skill_network.get("ok"),
                "n_targets": skill_network.get("n_targets"),
                "n_reachable": skill_network.get("n_reachable"),
                "required_egress": skill_network.get("required_egress"),
                "checked_at": skill_network.get("checked_at"),
            },
            "providers": {
                "ok": providers.get("ok"),
                "degraded": providers.get("degraded"),
                "n_providers": providers.get("n_providers"),
                "n_unhealthy": providers.get("n_unhealthy"),
                "n_invalid_model": providers.get("n_invalid_model"),
                "n_inference_failed": providers.get("n_inference_failed"),
                "state_model": providers.get("state_model"),
                "state_model_present": providers.get("state_model_present"),
                "checked_at": providers.get("checked_at"),
            },
        }

    @router.get("/metrics/providers", dependencies=deps)
    async def provider_metrics(window_s: int = 3600) -> dict[str, Any]:
        """LLM provider 健康预检指标 + 阈值告警。

        重点暴露"无效模型标识 / provider 健康失败 / 兜底链降级"这类静默故障。
        """
        from ...governance import observability as _obs

        health = _obs.query_provider_health(window_s)
        return {
            "status": "ok",
            "window_s": int(window_s),
            "health": health,
            "alerts": _obs.evaluate_provider_alerts(health),
        }

    @router.get("/metrics/council", dependencies=deps)
    async def council_metrics(window_s: int = 3600) -> dict[str, Any]:
        """L5 Council 复评指标：下修率 / 共识分布 / 平均调整量。"""
        from ...governance import observability as _obs

        return {"status": "ok", "window_s": int(window_s),
                "metrics": _obs.query_council_stats(window_s)}

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

        cs = _obs.query_council_stats(window_s)
        lines += [
            "# HELP more_os_council_reviews L5 council reviews in window.",
            "# TYPE more_os_council_reviews gauge",
            f"more_os_council_reviews {int(cs.get('reviews') or 0)}",
            "# HELP more_os_council_downgrade_rate Share of reviews that lowered confidence.",
            "# TYPE more_os_council_downgrade_rate gauge",
            f"more_os_council_downgrade_rate {float(cs.get('downgrade_rate') or 0.0)}",
            "# HELP more_os_council_avg_adjustment Mean confidence adjustment.",
            "# TYPE more_os_council_avg_adjustment gauge",
            f"more_os_council_avg_adjustment {float(cs.get('avg_adjustment') or 0.0)}",
        ]
        lines.append("# TYPE more_os_council_reviews_by_consensus gauge")
        for cons, n in (cs.get("by_consensus") or {}).items():
            safe = str(cons).replace('"', "")
            lines.append(f'more_os_council_reviews_by_consensus{{consensus="{safe}"}} {int(n)}')

        ph = _obs.query_provider_health(window_s)
        ok_val = ph.get("ok")
        lines += [
            "# HELP more_os_provider_preflight_ok Last LLM preflight passed.",
            "# TYPE more_os_provider_preflight_ok gauge",
            f"more_os_provider_preflight_ok {1 if ok_val else 0}",
            "# HELP more_os_provider_unhealthy Unhealthy LLM providers (last preflight).",
            "# TYPE more_os_provider_unhealthy gauge",
            f"more_os_provider_unhealthy {int(ph.get('n_unhealthy') or 0)}",
            "# HELP more_os_provider_invalid_model Providers whose configured model is missing.",
            "# TYPE more_os_provider_invalid_model gauge",
            f"more_os_provider_invalid_model {int(ph.get('n_invalid_model') or 0)}",
        ]
        lines.append("# TYPE more_os_provider_healthy gauge")
        for prov in ph.get("providers") or []:
            safe = str(prov.get("name") or "?").replace('"', "")
            hv = 1 if prov.get("healthy") else 0
            lines.append(f'more_os_provider_healthy{{provider="{safe}"}} {hv}')
        lines.append("# TYPE more_os_provider_model_present gauge")
        for prov in ph.get("providers") or []:
            if prov.get("model_present") is None:
                continue
            safe = str(prov.get("name") or "?").replace('"', "")
            lines.append(
                f'more_os_provider_model_present{{provider="{safe}"}} '
                f'{1 if prov.get("model_present") else 0}'
            )
        lines.append("# TYPE more_os_provider_alerts gauge")
        for a in _obs.evaluate_provider_alerts(ph):
            code = str(a.get("code", "")).replace('"', "")
            lvl = str(a.get("level", "")).replace('"', "")
            lines.append(f'more_os_provider_alerts{{level="{lvl}",code="{code}"}} 1')

        sk = _obs.query_skill_stats(window_s)
        lines += [
            "# HELP more_os_skill_runs Skill executions in window.",
            "# TYPE more_os_skill_runs gauge",
            f"more_os_skill_runs {int(sk.get('runs') or 0)}",
            "# HELP more_os_skill_success_rate Skill execution success rate.",
            "# TYPE more_os_skill_success_rate gauge",
            f"more_os_skill_success_rate {float(sk.get('success_rate') or 0.0)}",
            "# HELP more_os_skill_avg_duration_ms Mean skill duration.",
            "# TYPE more_os_skill_avg_duration_ms gauge",
            f"more_os_skill_avg_duration_ms {float(sk.get('avg_duration_ms') or 0.0)}",
        ]
        sn = _obs.query_skill_network_health(window_s)
        lines += [
            "# HELP more_os_skill_network_targets Declared skill egress targets.",
            "# TYPE more_os_skill_network_targets gauge",
            f"more_os_skill_network_targets {int(sn.get('n_targets') or 0)}",
            "# HELP more_os_skill_network_reachable Reachable skill egress targets.",
            "# TYPE more_os_skill_network_reachable gauge",
            f"more_os_skill_network_reachable {int(sn.get('n_reachable') or 0)}",
        ]
        lines.append("# TYPE more_os_skill_network_alerts gauge")
        for a in _obs.evaluate_skill_network_alerts(sn):
            code = str(a.get("code", "")).replace('"', "")
            lvl = str(a.get("level", "")).replace('"', "")
            lines.append(f'more_os_skill_network_alerts{{level="{lvl}",code="{code}"}} 1')
        lines.append("# TYPE more_os_skill_runs_by_skill gauge")
        for sid, slot in (sk.get("by_skill") or {}).items():
            safe = str(sid).replace('"', "")
            lines.append(
                f'more_os_skill_runs_by_skill{{skill="{safe}",'
                f'result="success"}} {int(slot.get("success") or 0)}'
            )
            lines.append(
                f'more_os_skill_runs_by_skill{{skill="{safe}",'
                f'result="failed"}} {int(slot.get("calls", 0) - slot.get("success", 0))}'
            )
        return PlainTextResponse("\n".join(lines) + "\n")

    @router.get("/metrics/skills", dependencies=deps)
    async def skill_metrics(window_s: int = 3600) -> dict[str, Any]:
        """技能执行指标：调用数 / 成功率 / 耗时（p95）+ 管理端注册统计。"""
        from ...governance import observability as _obs

        return {
            "status": "ok",
            "window_s": int(window_s),
            "metrics": _obs.query_skill_stats(window_s),
            "registry": core.skill_manager.get_stats(),
        }

    @router.get("/metrics/skill-network", dependencies=deps)
    async def skill_network_metrics(window_s: int = 3600) -> dict[str, Any]:
        """技能出网可达性自检结果 + 告警（R-4）。"""
        from ...governance import observability as _obs

        health = _obs.query_skill_network_health(window_s)
        return {
            "status": "ok",
            "window_s": int(window_s),
            "health": health,
            "alerts": _obs.evaluate_skill_network_alerts(health),
        }

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
