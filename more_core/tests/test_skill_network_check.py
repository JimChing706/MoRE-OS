"""R-4：技能出网可达性自检测试。"""

from __future__ import annotations

import pytest

from more_core.governance import observability as obs
from more_core.skills import create_default_skill_manager
from more_core.skills.base import SkillCategory, SkillMetadata
from more_core.skills.network_check import check_skill_network


class _Mgr:
    def __init__(self, metas):
        self._m = metas

    def list_skills(self):
        return self._m


def _meta(sid, *, egress=True, targets=None):
    return SkillMetadata(
        id=sid, name=sid, description="d", category=SkillCategory.WEB,
        deployment={
            "network_egress": egress,
            "network_targets": targets or ["example.com:443"],
        },
    )


@pytest.mark.asyncio
async def test_reachable_when_dns_and_tcp_ok(monkeypatch):
    from more_core.skills import network_check as nc

    async def dns_ok(host):
        return True, ""

    async def tcp_ok(host, port):
        return True, "", 12.5

    monkeypatch.setattr(nc, "_dns_ok", dns_ok)
    monkeypatch.setattr(nc, "_tcp_ok", tcp_ok)

    report = await check_skill_network(_Mgr([_meta("web.search")]))
    assert report["ok"] is True
    assert report["targets"][0]["reachable"] is True
    assert report["warnings"] == []


@pytest.mark.asyncio
async def test_unreachable_when_dns_fails(monkeypatch):
    from more_core.skills import network_check as nc

    async def dns_fail(host):
        return False, "gaierror: nodename nor servname provided"

    monkeypatch.setattr(nc, "_dns_ok", dns_fail)

    report = await check_skill_network(_Mgr([_meta("web.search")]))
    assert report["ok"] is False
    assert report["targets"][0]["dns_ok"] is False
    assert report["warnings"], "不可达必须给出告警"


@pytest.mark.asyncio
async def test_partial_reachability_is_flagged(monkeypatch):
    from more_core.skills import network_check as nc

    async def dns_ok(host):
        return True, ""

    async def tcp(host, port):
        return (host == "example.com"), "", 5.0

    monkeypatch.setattr(nc, "_dns_ok", dns_ok)
    monkeypatch.setattr(nc, "_tcp_ok", tcp)

    report = await check_skill_network(
        _Mgr([_meta("a", targets=["example.com:443"]),
              _meta("b", targets=["down.example:443"])])
    )
    assert report["ok"] is False
    assert any("部分出网目标不可达" in w for w in report["warnings"])


@pytest.mark.asyncio
async def test_non_egress_skills_are_ignored(monkeypatch):
    from more_core.skills import network_check as nc

    async def dns_ok(host):
        raise AssertionError("不应探测非出网技能")

    monkeypatch.setattr(nc, "_dns_ok", dns_ok)
    report = await check_skill_network(_Mgr([_meta("code.execute", egress=False)]))
    assert report["targets"] == []
    assert report["required_egress"] == []


def test_default_skills_declare_egress_targets():
    metas = {m.id: m for m in create_default_skill_manager().list_skills()}
    for sid in ("web.search", "web.browse", "api.call"):
        assert metas[sid].deployment.get("network_egress") is True
        assert metas[sid].deployment.get("network_targets")
    for sid in ("code.execute", "data.analyze"):
        assert not metas[sid].deployment.get("network_egress")


# ---------------------------------------------------------------------------
# 遥测 + 告警
# ---------------------------------------------------------------------------


def test_network_snapshot_roundtrip():
    obs.record_skill_network({
        "ok": False,
        "required_egress": ["web.search"],
        "targets": [
            {"skill_id": "web.search", "target": "example.com:443",
             "dns_ok": False, "tcp_ok": False, "reachable": False,
             "error": "gaierror", "latency_ms": 0.0},
        ],
        "warnings": ["所有出网技能目标均不可达（1 个）"],
    })
    h = obs.query_skill_network_health(3600)
    assert h["n_targets"] == 1
    assert h["n_reachable"] == 0
    assert h["ok"] is False
    assert h["required_egress"] == ["web.search"]


def test_network_alerts_critical_when_none_reachable():
    alerts = obs.evaluate_skill_network_alerts({
        "checked_at": 1.0, "n_targets": 2, "n_reachable": 0,
        "targets": [{"reachable": False}, {"reachable": False}],
        "required_egress": ["web.search"],
    })
    assert [a["code"] for a in alerts] == ["skill_network_unreachable"]
    assert alerts[0]["level"] == "critical"


def test_network_alerts_warning_when_partial():
    alerts = obs.evaluate_skill_network_alerts({
        "checked_at": 1.0, "n_targets": 2, "n_reachable": 1,
        "targets": [{"reachable": True}, {"reachable": False}],
    })
    assert alerts[0]["code"] == "skill_network_partial"
    assert alerts[0]["level"] == "warning"


def test_network_alerts_empty_when_all_reachable():
    assert obs.evaluate_skill_network_alerts({
        "checked_at": 1.0, "n_targets": 1, "n_reachable": 1,
        "targets": [{"reachable": True}],
    }) == []


def test_network_alerts_missing_snapshot():
    alerts = obs.evaluate_skill_network_alerts(obs.query_skill_network_health(3600))
    assert alerts[0]["code"] == "skill_network_preflight_missing"


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_skill_network_endpoint_and_overview(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        obs.record_skill_network({
            "ok": False, "required_egress": ["web.search"],
            "targets": [{"skill_id": "web.search", "target": "example.com:443",
                         "reachable": False, "dns_ok": False, "tcp_ok": False,
                         "error": "gaierror", "latency_ms": 0.0}],
            "warnings": ["不可达"],
        })
        resp = client.get("/api/v1/metrics/skill-network?window_s=3600")
        assert resp.status_code == 200
        body = resp.json()
        assert body["health"]["n_reachable"] == 0
        assert any(a["code"] == "skill_network_unreachable" for a in body["alerts"])

        ov = client.get("/api/v1/metrics/overview?window_s=3600").json()
        assert "skill_network" in ov


@pytest.mark.asyncio
async def test_core_start_runs_skill_network_preflight(core, monkeypatch):
    """启动时应执行技能出网自检（可探测函数被 mock，不触网）。"""
    monkeypatch.delenv("MORE_SKIP_SKILL_NETWORK_PREFLIGHT", raising=False)
    seen: dict[str, object] = {}

    async def fake_check(mgr):
        seen["called"] = True
        return {"ok": True, "required_egress": ["web.search"], "targets": [], "warnings": []}

    from more_core.skills import network_check

    monkeypatch.setattr(network_check, "check_skill_network", fake_check)
    await core.start()

    assert seen.get("called") is True
    assert obs.query_skill_network_health(3600)["checked_at"] > 0


def test_stale_skill_network_snapshot_is_info():
    import time as _t

    obs.record_skill_network({
        "ok": True, "required_egress": ["web.search"],
        "targets": [{"skill_id": "web.search", "target": "x:443", "reachable": True}],
        "warnings": [],
    })
    conn = obs._get_conn()
    conn.execute("UPDATE skill_network_snapshots SET ts = ?", (_t.time() - 7200,))

    h = obs.query_skill_network_health(3600)
    assert h["stale"] is True
    assert h["n_targets"] == 1, "过期快照仍应可读（此前返回空 → 误报 missing）"

    alerts = obs.evaluate_skill_network_alerts(h)
    assert alerts[0]["code"] == "skill_network_preflight_stale"
    assert alerts[0]["level"] == "info"
