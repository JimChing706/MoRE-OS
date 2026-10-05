"""LLM provider 健康预检可观测性测试（无效模型标识 / 健康失败 / 兜底链降级）。

对应"生产效率事故"：``MORE_LMSTUDIO_MODEL=local-model`` 占位符导致该模型 0%
成功，但此前无任何告警。本测试固化：预检能检出 → 落库 → 聚合 → 告警 → 看板/接口。
"""

from __future__ import annotations

import pytest

from more_core.governance import observability as obs

pytest.importorskip("fastapi")


# ---------------------------------------------------------------------------
# 1. 预检检测能力（离线，monkeypatch 掉模型列举的网络调用）
# ---------------------------------------------------------------------------


class _Prov:
    def __init__(self, name, model, base="http://x", healthy=True):
        self.name = name
        self.model = model
        self._base = base
        self._healthy = healthy

    async def health(self):
        return self._healthy


class _LLM:
    def __init__(self, providers, fallback):
        self._providers = {p.name: p for p in providers}
        self._fallback = fallback

    def list_providers(self):
        return list(self._providers)


@pytest.mark.asyncio
async def test_preflight_flags_invalid_model_identifier(monkeypatch):
    from more_core.llm import preflight as pf

    async def fake_fetch(url):
        return ["gpt-oss-20b", "gemma-4-26b"]  # 配置的 local-model 不在其中

    monkeypatch.setattr(pf, "_fetch_models", fake_fetch)
    llm = _LLM([_Prov("lmstudio", "local-model")], ["lmstudio"])
    report = await pf.preflight_llm(llm, ["lmstudio"])

    check = report.providers[0]
    assert check.model_present is False
    assert report.ok is False
    assert any("not found" in w for w in check.warnings)
    assert any("local-model" in w for w in report.warnings)


class _State:
    def __init__(self, provider, model):
        self.provider = provider
        self.model = model


class _StateMgr:
    def __init__(self, state):
        self._s = state

    def get_state(self):
        return self._s


def _patch_state(monkeypatch, provider, model):
    from more_core.llm import state_manager as sm

    monkeypatch.setattr(sm, "get_llm_state_manager", lambda: _StateMgr(_State(provider, model)))


@pytest.mark.asyncio
async def test_preflight_ok_when_models_present_and_chain_healthy(monkeypatch):
    from more_core.llm import preflight as pf

    async def fake_fetch(url):
        return ["m"]

    monkeypatch.setattr(pf, "_fetch_models", fake_fetch)
    _patch_state(monkeypatch, "a", "m")  # 生效模型也在服务端列表中
    llm = _LLM([_Prov("a", "m"), _Prov("b", "m")], ["a", "b"])
    report = await pf.preflight_llm(llm, ["a", "b"])

    assert all(p.model_present for p in report.providers)
    assert report.state_model_present is True
    assert report.degraded is False
    assert report.ok is True


@pytest.mark.asyncio
async def test_preflight_flags_invalid_effective_state_model(monkeypatch):
    """配置漂移：provider 自身模型正确，但 state manager 生效模型不存在。

    这正是本机事故的形态（provider=ornith，生效=local-model）——只查 provider
    会给出"假绿灯"。
    """
    from more_core.llm import preflight as pf

    async def fake_fetch(url):
        return ["ornith-1.5-35b-a3b"]

    monkeypatch.setattr(pf, "_fetch_models", fake_fetch)
    _patch_state(monkeypatch, "lmstudio", "local-model")

    llm = _LLM([_Prov("lmstudio", "ornith-1.5-35b-a3b")], ["lmstudio"])
    report = await pf.preflight_llm(llm, ["lmstudio"])

    assert report.providers[0].model_present is True   # provider 配置没错
    assert report.state_model == "local-model"
    assert report.state_model_present is False          # 生效模型错了
    assert report.ok is False
    assert any("local-model" in w and "[state]" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# 2. 落库 / 聚合
# ---------------------------------------------------------------------------


def _bad_report():
    return {
        "ok": False, "degraded": True,
        "providers": [{
            "name": "lmstudio", "registered": True, "endpoint": "http://x",
            "configured_model": "local-model", "models_available": 2,
            "model_present": False, "healthy": False, "warnings": ["model not found"],
        }],
        "fallback_chain": ["lmstudio", "ollama"],
        "chain_registered": ["lmstudio"],
        "warnings": ["[lmstudio] configured model 'local-model' not found"],
    }


def test_provider_health_snapshot_roundtrip():
    obs.record_provider_health(_bad_report())
    h = obs.query_provider_health(3600)

    assert h["n_providers"] == 1
    assert h["n_unhealthy"] == 1
    assert h["n_invalid_model"] == 1
    assert h["degraded"] is True
    assert h["ok"] is False
    assert h["providers"][0]["name"] == "lmstudio"
    assert h["chain_declared"] == ["lmstudio", "ollama"]
    assert h["snapshots"] == 1


def test_provider_health_latest_snapshot_wins():
    obs.record_provider_health(_bad_report())
    obs.record_provider_health({
        "ok": True, "degraded": False,
        "providers": [{"name": "lmstudio", "healthy": True, "model_present": True}],
        "fallback_chain": ["lmstudio", "ollama"],
        "chain_registered": ["lmstudio", "ollama"], "warnings": [],
    })
    h = obs.query_provider_health(3600)
    assert h["ok"] is True
    assert h["n_invalid_model"] == 0
    assert h["snapshots"] == 2


def test_provider_health_empty_is_zero_not_error():
    h = obs.query_provider_health(3600)
    assert h["n_providers"] == 0
    assert h["checked_at"] == 0.0
    assert "error" not in h


# ---------------------------------------------------------------------------
# 3. 阈值告警（纯函数）
# ---------------------------------------------------------------------------


def _health(providers, degraded=False, chain_declared=None, chain_registered=None):
    return {
        "checked_at": 1.0, "ok": not providers, "degraded": degraded,
        "n_providers": len(providers), "providers": providers,
        "chain_declared": chain_declared or [], "chain_registered": chain_registered or [],
    }


def test_invalid_model_is_critical():
    alerts = obs.evaluate_provider_alerts(_health(
        [{"name": "lmstudio", "configured_model": "local-model",
          "model_present": False, "healthy": False}],
        chain_declared=["lmstudio"], chain_registered=["lmstudio"],
    ))
    codes = {a["code"] for a in alerts}
    assert "provider_invalid_model" in codes
    assert "provider_unhealthy" in codes
    crit = [a for a in alerts if a["code"] in ("provider_invalid_model", "provider_unhealthy")]
    assert all(a["level"] == "critical" for a in crit)


def test_state_invalid_model_is_critical():
    alerts = obs.evaluate_provider_alerts({
        "checked_at": 1.0, "n_providers": 1, "degraded": False,
        "providers": [{"name": "lmstudio", "healthy": True, "model_present": True}],
        "state_provider": "lmstudio", "state_model": "local-model",
        "state_model_present": False,
        "chain_declared": ["lmstudio"], "chain_registered": ["lmstudio"],
    })
    hit = [a for a in alerts if a["code"] == "state_invalid_model"]
    assert hit and hit[0]["level"] == "critical"


def test_state_invalid_model_counts_as_invalid():
    obs.record_provider_health({
        "ok": False, "degraded": False,
        "providers": [{"name": "lmstudio", "healthy": True, "model_present": True}],
        "state_provider": "lmstudio", "state_model": "local-model",
        "state_model_present": False,
        "fallback_chain": ["lmstudio", "ollama"],
        "chain_registered": ["lmstudio", "ollama"], "warnings": ["[state] ..."],
    })
    assert obs.query_provider_health(3600)["n_invalid_model"] == 1


def test_degraded_chain_is_warning():
    alerts = obs.evaluate_provider_alerts(_health(
        [{"name": "a", "healthy": True, "model_present": True}],
        degraded=True, chain_declared=["a", "b"], chain_registered=["a"],
    ))
    assert any(a["code"] == "fallback_chain_degraded" and a["level"] == "warning" for a in alerts)


def test_healthy_providers_produce_no_alerts():
    alerts = obs.evaluate_provider_alerts(_health(
        [{"name": "a", "healthy": True, "model_present": True},
         {"name": "b", "healthy": True, "model_present": True}],
        chain_declared=["a", "b"], chain_registered=["a", "b"],
    ))
    assert alerts == []


def test_missing_snapshot_hints_to_run_preflight():
    alerts = obs.evaluate_provider_alerts(obs.query_provider_health(3600))
    assert any(a["code"] == "provider_preflight_missing" for a in alerts)


# ---------------------------------------------------------------------------
# 4. 接口：JSON + Prometheus
# ---------------------------------------------------------------------------


def test_provider_metrics_endpoint(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        # 注意：TestClient 启动 lifespan 会调 core.start() 并记录一条预检快照，
        # 因此播种必须在其之后，才能成为"最新快照"。
        obs.record_provider_health(_bad_report())
        resp = client.get("/api/v1/metrics/providers?window_s=3600")
    assert resp.status_code == 200
    body = resp.json()
    assert body["health"]["n_invalid_model"] == 1
    assert any(a["code"] == "provider_invalid_model" for a in body["alerts"])


def test_prometheus_exports_provider_metrics(core):
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app

    with TestClient(create_app(core)) as client:
        obs.record_provider_health(_bad_report())
        resp = client.get("/api/v1/metrics/governance/prometheus?window_s=3600")
    assert resp.status_code == 200
    body = resp.text
    assert "more_os_provider_invalid_model 1" in body
    assert "more_os_provider_unhealthy 1" in body
    assert 'more_os_provider_model_present{provider="lmstudio"} 0' in body
    assert 'more_os_provider_alerts{level="critical",code="provider_invalid_model"} 1' in body


def test_preflight_endpoint_records_snapshot(core, monkeypatch):
    """按需复检会写库（使看板可刷新）。"""
    from fastapi.testclient import TestClient

    from more_core.api.server import create_app
    from more_core.llm import preflight as pf
    from more_core.llm.preflight import LLMPreflight, ProviderCheck

    async def fake_preflight(llm, chain=None):
        r = LLMPreflight()
        r.providers = [ProviderCheck(
            name="a", registered=True, configured_model="m",
            model_present=True, healthy=True, models_available=1,
        )]
        r.fallback_chain = ["a"]
        r.chain_registered = ["a"]
        return r

    monkeypatch.setattr(pf, "preflight_llm", fake_preflight)
    with TestClient(create_app(core)) as client:
        before = obs.query_provider_health(3600)["snapshots"]
        resp = client.get("/api/v1/llm/preflight")
    assert resp.status_code == 200

    h = obs.query_provider_health(3600)
    assert h["snapshots"] == before + 1   # 按需复检写入了新快照
    assert h["n_providers"] == 1
    assert h["n_invalid_model"] == 0
