"""API-key 分派与使用管理（归属 / 配额 / 用量 / 关注清单）回归测试。"""

from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from more_core.security.api_key_store import APIKeyStore, set_default_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MORE_API_KEY_PEPPER", "unit-pepper")
    s = APIKeyStore(tmp_path / "keys.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 分派（归属绑定）
# ---------------------------------------------------------------------------


def test_dispatch_batch_binds_owner_consumer_and_quota(store):
    out = store.dispatch_batch(
        [
            {"owner": "team-a", "consumer": "ci-runner", "label": "ci",
             "scopes": ["tasks:execute"], "quota_per_min": 10},
            {"owner": "team-b", "consumer": "dashboard", "ttl_seconds": 3600},
        ],
        default_scopes=["tasks:execute"],
        issued_by="env-key-principal",
        channel="api",
    )
    assert len(out) == 2
    a, b = out[0]["key"], out[1]["key"]
    assert a["owner"] == "team-a" and a["consumer"] == "ci-runner"
    assert a["quota_per_min"] == 10 and a["issued_by"] == "env-key-principal"
    assert a["channel"] == "api"
    assert b["consumer"] == "dashboard" and b["quota_per_min"] is None
    # 明文只在返回中出现，库里查不到
    assert out[0]["api_key"] not in str(store.list_keys())


def test_dispatch_batch_uses_defaults(store):
    out = store.dispatch_batch([{"consumer": "svc"}], default_scopes=["tasks:execute"],
                               default_ttl_seconds=600)
    rec = out[0]["key"]
    assert rec["scopes"] == ["tasks:execute"]
    assert rec["expires_at"] is not None


# ---------------------------------------------------------------------------
# 用量记录与报表
# ---------------------------------------------------------------------------


def test_record_usage_accumulates_counters(store):
    _raw, rec = store.register(label="x", scopes=["tasks:execute"])
    for i in range(3):
        store.record_usage(rec.key_id, endpoint="/api/v1/tasks/execute",
                           status=200 if i < 2 else 500, latency_ms=100 + i, tokens=10,
                           ip="10.0.0.1")
    got = store.get(rec.key_id)
    assert got.call_count == 3
    assert got.tokens_used == 30
    assert got.denied_count == 1
    assert got.first_used_at and got.last_used_at
    assert got.first_used_at <= got.last_used_at
    assert got.last_used_ip == "10.0.0.1"


def test_usage_report_shape_and_percentiles(store):
    _raw, rec = store.register(label="x", scopes=["tasks:execute"])
    for lat in (100, 200, 300, 400):
        store.record_usage(rec.key_id, endpoint="/a", status=200,
                           latency_ms=lat, tokens=5, ip="1.1.1.1")
    store.record_usage(rec.key_id, endpoint="/b", status=500, latency_ms=500)

    u = store.usage(rec.key_id, window_s=3600)
    assert u["calls"] == 5
    assert u["success"] == 4 and u["failures"] == 1
    assert u["success_rate"] == 0.8
    assert u["tokens"] == 20
    assert u["latency_ms"]["max"] == 500
    assert u["by_endpoint"]["/a"] == 4
    assert u["owner"] == "" and u["quota"]["limit_per_min"] is None


def test_usage_overview_ranks_by_calls(store):
    _r1, a = store.register(label="a", owner="t1", consumer="c1")
    _r2, b = store.register(label="b", owner="t2", consumer="c2")
    for _ in range(5):
        store.record_usage(a.key_id, endpoint="/x", status=200)
    for _ in range(2):
        store.record_usage(b.key_id, endpoint="/x", status=200)
    ov = store.usage_overview(window_s=3600)
    assert ov["total_calls"] == 7
    assert ov["keys"][0]["key_id"] == a.key_id
    assert ov["keys"][0]["owner"] == "t1"
    assert ov["keys"][0]["calls"] == 5


# ---------------------------------------------------------------------------
# 配额
# ---------------------------------------------------------------------------


def test_quota_check_allows_until_limit(store):
    _raw, rec = store.register(label="q", quota_per_min=2)
    allowed, used, limit = store.quota_check(rec.key_id)
    assert allowed is True and used == 0 and limit == 2
    store.record_usage(rec.key_id, endpoint="/x", status=200)
    store.record_usage(rec.key_id, endpoint="/x", status=200)
    allowed, used, limit = store.quota_check(rec.key_id)
    assert allowed is False and used == 2 and limit == 2


def test_quota_unlimited_when_not_set(store):
    _raw, rec = store.register(label="u")
    allowed, _used, limit = store.quota_check(rec.key_id)
    assert allowed is True and limit is None


def test_quota_window_expiry(store):
    _raw, rec = store.register(label="w", quota_per_min=1)
    old = time.time() - 120
    store.record_usage(rec.key_id, endpoint="/x", status=200, ts=old)
    allowed, used, _limit = store.quota_check(rec.key_id)
    assert allowed is True and used == 0


def test_record_denied_does_not_extend_window(store):
    _raw, rec = store.register(label="d", quota_per_min=1)
    store.record_usage(rec.key_id, endpoint="/x", status=200)
    for _ in range(5):
        store.record_denied(rec.key_id, ip="9.9.9.9")
    allowed, used, _limit = store.quota_check(rec.key_id)
    assert allowed is False and used == 1  # 拒绝不写入明细窗口
    assert store.get(rec.key_id).denied_count == 5


# ---------------------------------------------------------------------------
# 关注清单 / 清理
# ---------------------------------------------------------------------------


def test_attention_flags_unused_and_expiring(store):
    store.register(label="unused")                       # 从未使用
    _raw, soon = store.register(label="soon", ttl_seconds=3600)
    att = store.attention(expiry_days=2, stale_days=0)
    assert att["counts"]["never_used"] >= 2
    assert att["counts"]["expiring_soon"] >= 1
    assert any(k["key_id"] == soon.key_id for k in att["expiring_soon"])


def test_prune_usage_removes_old_rows(store):
    _raw, rec = store.register(label="p")
    store.record_usage(rec.key_id, endpoint="/old", status=200,
                       ts=time.time() - 10 * 86400)
    store.record_usage(rec.key_id, endpoint="/new", status=200)
    removed = store.prune_usage(keep_days=7)
    assert removed == 1
    assert store.usage(rec.key_id, window_s=30 * 86400)["calls"] == 1
    assert store.get(rec.key_id).call_count == 2  # 聚合计数保留


# ---------------------------------------------------------------------------
# HTTP 层：配额生效 + 归属可查
# ---------------------------------------------------------------------------


def test_http_quota_enforced_with_429(store, monkeypatch):
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    from more_core.api.server import _require_api_key

    raw, rec = store.register(label="http-quota", scopes=["tasks:execute"], quota_per_min=2)
    set_default_store(store)

    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(_require_api_key)])
    async def probe(request: Request):
        return {"principal": request.state.principal}

    client = TestClient(app)
    h = {"Authorization": f"Bearer {raw}"}

    # 依赖通过后自行记账（真实链路由中间件记录）
    assert client.get("/probe", headers=h).status_code == 200
    store.record_usage(rec.key_id, endpoint="/probe", status=200)
    assert client.get("/probe", headers=h).status_code == 200
    store.record_usage(rec.key_id, endpoint="/probe", status=200)

    r = client.get("/probe", headers=h)
    assert r.status_code == 429
    assert "quota exceeded" in r.json()["detail"]
    assert store.get(rec.key_id).denied_count == 1
    set_default_store(None)
