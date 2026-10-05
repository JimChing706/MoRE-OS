"""LLM 路由测试（api/routers/llm.py 覆盖补齐）。

注意：state/update 会改全局 LLMStateManager → 用例内保存并还原。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app


@pytest.fixture()
def client(core):
    with TestClient(create_app(core)) as c:
        yield c


@pytest.fixture()
def isolated_state():
    from more_core.llm.state_manager import get_llm_state_manager

    mgr = get_llm_state_manager()
    original = dict(mgr.get_state().__dict__)
    yield mgr
    mgr.update_state(**original)


# ---------------------------------------------------------------------------
# 只读端点
# ---------------------------------------------------------------------------


def test_llm_health_and_state(client):
    # /llm/health 返回 {provider: bool} 映射
    health = client.get("/api/v1/llm/health").json()
    assert isinstance(health, dict)
    assert all(isinstance(v, bool) for v in health.values())

    state = client.get("/api/v1/llm/state").json()
    assert "current_state" in state and "usage" in state

    cur = client.get("/api/v1/llm/state/current").json()
    for key in ("provider", "model", "temperature", "max_tokens", "timeout_s"):
        assert key in cur


def test_llm_usage_providers_history(client):
    # /llm/usage 是扁平结构（total_requests 等直接挂在顶层）
    usage = client.get("/api/v1/llm/usage").json()
    assert {"total_requests", "total_tokens", "avg_latency_ms"} <= set(usage)

    providers = client.get("/api/v1/llm/providers").json()
    assert "providers" in providers

    history = client.get("/api/v1/llm/history?limit=5").json()
    assert "history" in history


def test_llm_reasoning_endpoints(client):
    assert "config" in client.get("/api/v1/llm/reasoning").json()

    check = client.get("/api/v1/llm/reasoning/check?model=deepseek-reasoner").json()
    assert check["model"] == "deepseek-reasoner" and "is_reasoning" in check

    updated = client.post(
        "/api/v1/llm/reasoning/config", json={"enabled": True}
    ).json()
    assert updated["success"] is True


def test_llm_aliases_list_and_resolve(client, core):
    # /llm/aliases 返回别名列表
    aliases = client.get("/api/v1/llm/aliases").json()
    assert isinstance(aliases, list) and aliases
    assert {"alias", "provider", "model"} <= set(aliases[0])

    assert client.get("/api/v1/llm/aliases/resolve/nope-not-an-alias").status_code == 404


def test_llm_routing_config_and_rollup(client):
    cfg = client.get("/api/v1/llm/routing").json()
    assert "bindings" in cfg and "fallback_chains" in cfg

    rolled = client.get("/api/v1/llm/routing?tier_transitions_rollup=1h").json()
    assert "tier_transitions_rollup" in rolled

    assert client.get(
        "/api/v1/llm/routing?tier_transitions_rollup=bogus"
    ).status_code == 400


# ---------------------------------------------------------------------------
# state/update（含校验）
# ---------------------------------------------------------------------------


def test_state_update_valid(client, isolated_state):
    body = client.post("/api/v1/llm/state/update", json={"temperature": 0.3}).json()
    assert body["success"] is True
    assert body["updated"]["temperature"] == pytest.approx(0.3)
    assert isolated_state.get_state().temperature == pytest.approx(0.3)


def test_state_update_ignores_unknown_keys(client, isolated_state):
    body = client.post(
        "/api/v1/llm/state/update", json={"not_a_field": 1, "temperature": 0.9}
    ).json()
    assert body["updated"] == {"temperature": 0.9}


@pytest.mark.parametrize(
    "payload,needle",
    [
        ({"temperature": 5}, "temperature: must be <= 2.0"),
        ({"temperature": "hot"}, "temperature: expected float"),
        ({"max_tokens": 0}, "max_tokens: must be >= 1"),
        ({"retry_count": 99}, "retry_count: must be <= 10"),
        ({"lmstudio_endpoint": "ftp://x"}, "valid http(s) URL"),
    ],
)
def test_state_update_validation_errors(client, payload, needle):
    resp = client.post("/api/v1/llm/state/update", json=payload)
    assert resp.status_code == 422
    assert needle in resp.json()["detail"]


def test_state_reset(client, isolated_state):
    client.post("/api/v1/llm/state/update", json={"temperature": 1.9})
    body = client.post("/api/v1/llm/state/reset").json()
    assert body["success"] is True
    assert "temperature" in body["reset_to"]


# ---------------------------------------------------------------------------
# routing 写操作
# ---------------------------------------------------------------------------


def test_routing_update_task_binding(client):
    body = client.post(
        "/api/v1/llm/routing",
        json={"task_type": "nlp_task", "provider": "lmstudio", "model": "m1"},
    ).json()
    assert body["success"] is True
    assert body["provider"] == "lmstudio"

    assert client.post(
        "/api/v1/llm/routing", json={"task_type": "nlp_task"}
    ).status_code == 422

    assert client.post(
        "/api/v1/llm/routing", json={"task_type": "nope", "provider": "p", "model": "m"}
    ).status_code == 400


def test_routing_update_chain_and_delete(client):
    body = client.post(
        "/api/v1/llm/routing",
        json={"chain": "my_chain", "pairs": [{"provider": "lmstudio", "model": "m"}]},
    ).json()
    assert body["success"] is True and body["chain"] == "my_chain"

    assert client.post("/api/v1/llm/routing", json={}).status_code == 422

    deleted = client.delete("/api/v1/llm/routing/chain/my_chain").json()
    assert deleted["removed"] == "my_chain"
