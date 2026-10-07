"""技能出网可达性自检（R-4）。

部分技能声明 ``deployment.network_egress=True``（web.search / web.browse / api.call），
在无外网/DNS 受限的部署环境里它们会整片不可用。此前只能等调用时才报 DNS 错误。

本模块在启动时对声明目标做**轻量可达性探测**（DNS 解析 + TCP 连接，不做真实业务请求），
结果落库 observability 并在看板/告警中暴露，使"网络不可达"提前可见。
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

__all__ = ["DEFAULT_NETWORK_TARGETS", "check_skill_network"]

# 通用"公网可达"代表目标（未单独声明 network_targets 的出网技能用它）
DEFAULT_NETWORK_TARGETS: tuple[str, ...] = ("example.com:443",)

_PROBE_TIMEOUT_S = 3.0


def _split_target(target: str) -> tuple[str, int]:
    host, _, port = target.partition(":")
    return host.strip(), int(port or "443")


async def _dns_ok(host: str) -> tuple[bool, str]:
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, socket.getaddrinfo, host, None)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都算不可达
        return False, f"{type(exc).__name__}: {exc}"


async def _tcp_ok(host: str, port: int) -> tuple[bool, str, float]:
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT_S
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # pragma: no cover - 关闭异常忽略  # noqa: BLE001, S110
            pass
        del reader
        return True, "", (time.perf_counter() - start) * 1000
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", (time.perf_counter() - start) * 1000


async def check_skill_network(skill_manager: Any) -> dict[str, Any]:
    """探测所有出网技能的声明目标可达性，返回结构化报告。

    报告结构::

        {
          "ok": bool,               # 所有出网技能都可达
          "required_egress": [...],  # 声明 network_egress 的技能 id
          "targets": [{skill_id, target, dns_ok, tcp_ok, reachable, error, latency_ms}],
          "checked_at": ts,
          "warnings": [...],
        }
    """
    targets: list[dict[str, Any]] = []
    required: list[str] = []
    warnings: list[str] = []

    try:
        metas = skill_manager.list_skills()
    except Exception as exc:  # pragma: no cover - 防御  # noqa: BLE001
        return {
            "ok": False,
            "required_egress": [],
            "targets": [],
            "checked_at": time.time(),
            "warnings": [f"list_skills failed: {exc}"],
        }

    seen: set[tuple[str, str]] = set()
    for meta in metas:
        deploy = meta.deployment or {}
        if not deploy.get("network_egress"):
            continue
        required.append(meta.id)
        declared = list(deploy.get("network_targets") or DEFAULT_NETWORK_TARGETS)
        for target in declared:
            key = (meta.id, target)
            if key in seen:
                continue
            seen.add(key)
            host, port = _split_target(str(target))
            dns_ok, dns_err = await _dns_ok(host)
            if not dns_ok:
                targets.append(
                    {
                        "skill_id": meta.id,
                        "target": target,
                        "dns_ok": False,
                        "tcp_ok": False,
                        "reachable": False,
                        "error": dns_err,
                        "latency_ms": 0.0,
                    }
                )
                continue
            tcp_ok, tcp_err, latency = await _tcp_ok(host, port)
            targets.append(
                {
                    "skill_id": meta.id,
                    "target": target,
                    "dns_ok": True,
                    "tcp_ok": tcp_ok,
                    "reachable": tcp_ok,
                    "error": tcp_err,
                    "latency_ms": round(latency, 1),
                }
            )

    reachable = [t for t in targets if t["reachable"]]
    ok = bool(targets) and len(reachable) == len(targets)
    if targets and not reachable:
        warnings.append(f"所有出网技能目标均不可达（{len(targets)} 个）——web/api 技能将不可用")
    elif reachable and len(reachable) < len(targets):
        unreachable = [t["target"] for t in targets if not t["reachable"]]
        warnings.append(f"部分出网目标不可达: {unreachable}")

    return {
        "ok": ok,
        "required_egress": required,
        "targets": targets,
        "checked_at": time.time(),
        "warnings": warnings,
    }
