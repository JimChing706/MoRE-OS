"""Tests for the managed API-key lifecycle (issue / verify / expire / rotate)."""

from __future__ import annotations

import sqlite3

import pytest

from more_core.security.api_key_store import (
    WILDCARD_SCOPE,
    APIKeyStore,
    set_default_store,
)

PEPPER = "unit-test-pepper"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MORE_API_KEY_PEPPER", PEPPER)
    s = APIKeyStore(tmp_path / "api_keys.db")
    yield s
    s.close()


def _issue(store: APIKeyStore, **kwargs):
    defaults = {"label": "unit", "scopes": ["tasks:execute"], "ttl_seconds": None}
    defaults.update(kwargs)
    return store.register(**defaults)


# ---------------------------------------------------------------------------
# storage / verification
# ---------------------------------------------------------------------------


def test_issue_and_verify_roundtrip(store):
    raw, record = _issue(store)
    assert raw.startswith("sk-more-os-")
    assert record.key_id.startswith("key_")
    assert record.active and not record.expired and not record.revoked

    verified = store.verify(raw)
    assert verified is not None
    assert verified.key_id == record.key_id
    assert verified.has_scope("tasks:execute")
    assert not verified.has_scope("admin:apikeys")


def test_wrong_and_empty_keys_are_rejected(store):
    raw, _ = _issue(store)
    assert store.verify("not-a-key") is None
    assert store.verify("") is None
    assert store.verify(None) is None
    # a neighbouring key must not validate
    assert store.verify(raw[:-1] + ("A" if raw[-1] != "A" else "B")) is None


def test_raw_secret_is_never_persisted(store):
    raw, _ = _issue(store)
    assert raw.encode() not in store.db_path.read_bytes()
    with sqlite3.connect(str(store.db_path)) as conn:
        hashes = [row[0] for row in conn.execute("SELECT key_hash FROM api_keys")]
    assert hashes and all(len(h) == 64 for h in hashes)
    assert raw not in hashes


def test_expired_key_is_rejected(store):
    raw, record = _issue(store, ttl_seconds=-1)
    assert record.expired
    assert store.verify(raw) is None


def test_revoked_key_is_rejected(store):
    raw, record = _issue(store)
    assert store.verify(raw) is not None
    assert store.revoke(record.key_id) is True
    assert store.verify(raw) is None
    assert store.revoke(record.key_id) is False  # already revoked


# ---------------------------------------------------------------------------
# rotation / expiry management
# ---------------------------------------------------------------------------


def test_rotation_with_grace_keeps_old_key_alive(store):
    old_raw, old = _issue(store)
    new_raw, new = store.rotate(old.key_id, grace_seconds=3600)
    assert new.key_id != old.key_id
    assert new.scopes == old.scopes
    assert store.verify(old_raw) is not None  # still inside grace window
    assert store.verify(new_raw) is not None
    assert store.get(new.key_id).rotated_from == old.key_id


def test_rotation_without_grace_retires_old_key(store):
    old_raw, old = _issue(store)
    new_raw, _ = store.rotate(old.key_id, grace_seconds=0)
    assert store.verify(old_raw) is None
    assert store.verify(new_raw) is not None


def test_rotate_unknown_key_returns_none(store):
    assert store.rotate("key_does_not_exist") is None


def test_purge_expired_removes_only_finished_keys(store):
    _alive_raw, alive = _issue(store, ttl_seconds=3600)
    _dead_raw, dead = _issue(store, ttl_seconds=-1)
    removed = store.purge_expired()
    ids = {rec.key_id for rec in store.list_keys()}
    assert removed >= 1
    assert alive.key_id in ids
    assert dead.key_id not in ids


def test_stats_and_listing(store):
    _issue(store, label="a", ttl_seconds=3600)
    _raw, revoked = _issue(store, label="b")
    store.revoke(revoked.key_id)
    stats = store.stats()
    assert stats["total"] == 2
    assert stats["active"] == 1
    assert stats["revoked"] == 1
    actives = store.list_keys(include_inactive=False)
    assert [r.key_id for r in actives] == [r.key_id for r in store.list_keys() if r.active]


def test_wildcard_scope_matches_everything(store):
    raw = "sk-more-os-" + "z" * 48
    store.issue(raw_key=raw, scopes=[WILDCARD_SCOPE])
    rec = store.verify(raw)
    assert rec.has_scope("anything:at:all")


def test_pepper_from_env_changes_the_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("MORE_API_KEY_PEPPER", "pepper-one")
    a = APIKeyStore(tmp_path / "a.db")
    monkeypatch.setenv("MORE_API_KEY_PEPPER", "pepper-two")
    b = APIKeyStore(tmp_path / "b.db")
    raw = "sk-more-os-" + "q" * 48
    rec_a = a.issue(raw_key=raw)
    rec_b = b.issue(raw_key=raw)
    assert rec_a._key_hash != rec_b._key_hash
    a.close()
    b.close()


# ---------------------------------------------------------------------------
# HTTP enforcement (minimal app — avoids booting the whole orchestrator)
# ---------------------------------------------------------------------------


def _client(store):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from more_core.api.auth import require_scope
    from more_core.api.server import _require_api_key

    set_default_store(store)
    app = FastAPI()

    @app.get("/open", dependencies=[Depends(_require_api_key)])
    async def _open():
        return {"ok": True}

    @app.post(
        "/execute",
        dependencies=[Depends(_require_api_key), Depends(require_scope("tasks:execute"))],
    )
    async def _execute():
        return {"ok": True}

    @app.post(
        "/admin",
        dependencies=[Depends(_require_api_key), Depends(require_scope("admin:apikeys"))],
    )
    async def _admin():
        return {"ok": True}

    return TestClient(app)


def test_http_requires_a_valid_key(store, monkeypatch):
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    raw, _ = _issue(store)
    client = _client(store)
    assert client.get("/open").status_code == 401
    assert client.get("/open", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.get("/open", headers={"Authorization": f"Bearer {raw}"}).status_code == 200


def test_http_scope_enforcement(store, monkeypatch):
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    scoped_raw, _ = _issue(store, scopes=["tasks:execute"])
    admin_raw, _ = _issue(store, scopes=["admin:apikeys"])
    client = _client(store)

    ok = {"Authorization": f"Bearer {scoped_raw}"}
    assert client.post("/execute", headers=ok).status_code == 200
    assert client.post("/admin", headers=ok).status_code == 403

    admin = {"Authorization": f"Bearer {admin_raw}"}
    assert client.post("/admin", headers=admin).status_code == 200
    assert client.post("/execute", headers=admin).status_code == 403


def test_http_rejects_revoked_and_expired_keys(store, monkeypatch):
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    revoked_raw, revoked = _issue(store)
    expired_raw, _ = _issue(store, ttl_seconds=-5)
    client = _client(store)
    store.revoke(revoked.key_id)

    assert (
        client.get("/open", headers={"Authorization": f"Bearer {revoked_raw}"}).status_code == 403
    )
    assert (
        client.get("/open", headers={"Authorization": f"Bearer {expired_raw}"}).status_code == 403
    )


def test_http_env_key_keeps_working_with_wildcard(store, monkeypatch):
    monkeypatch.setenv("MORE_API_KEY", "sk-more-os-legacy-env-key-000000000000000000")
    set_default_store(store)
    client = _client(store)
    headers = {"Authorization": "Bearer sk-more-os-legacy-env-key-000000000000000000"}
    assert client.post("/execute", headers=headers).status_code == 200
    assert client.post("/admin", headers=headers).status_code == 200
