"""Deployments 路由测试（api/routers/deployments.py 覆盖补齐）—— 用假 manager。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app
from more_core.deploy.manager import DeploymentStatus, DeploymentType


class _FakeDep:
    def __init__(self, dep_id="d1", dtype=DeploymentType.HAND, status=DeploymentStatus.RUNNING):
        self.id = dep_id
        self.type = dtype
        self.status = status

    def to_dict(self):
        return {"id": self.id, "type": self.type.value, "status": self.status.value}


class _FakeManager:
    def __init__(self) -> None:
        self.deps: dict[str, _FakeDep] = {}
        self.list_calls: list = []
        self.deployed: list[dict] = []
        self.restarted: list[str] = []
        self.undeployed: list[str] = []
        self.removed: list[str] = []

    def list_deployments(self, dt=None, ds=None):
        self.list_calls.append((dt, ds))
        return [d.to_dict() for d in self.deps.values()]

    def stats(self):
        return {"total": len(self.deps)}

    async def deploy(self, **kw):
        self.deployed.append(kw)
        dep = _FakeDep(kw.get("name", "d1"), dtype=kw.get("dtype", DeploymentType.HAND))
        self.deps[dep.id] = dep
        return dep

    def get(self, dep_id):
        return self.deps.get(dep_id)

    async def restart(self, dep_id):
        self.restarted.append(dep_id)
        return dep_id in self.deps

    async def undeploy(self, dep_id):
        self.undeployed.append(dep_id)
        return dep_id in self.deps

    async def remove(self, dep_id):
        self.removed.append(dep_id)
        return self.deps.pop(dep_id, None) is not None


@pytest.fixture()
def dm(core):
    fake = _FakeManager()
    core.deployment_manager = fake
    with TestClient(create_app(core)) as c:
        yield c, fake


def test_list_deployments_empty(dm):
    c, _ = dm
    body = c.get("/api/v1/deployments").json()
    assert body["deployments"] == [] and body["stats"] == {"total": 0}


def test_list_deployments_with_filters(dm):
    c, fake = dm
    fake.deps["d1"] = _FakeDep()
    body = c.get("/api/v1/deployments?dtype=hand&status=running").json()
    assert len(body["deployments"]) == 1
    assert fake.list_calls[-1] == (DeploymentType.HAND, DeploymentStatus.RUNNING)


@pytest.mark.parametrize(
    "query,needle",
    [("dtype=nope", "Invalid type"), ("status=nope", "Invalid status")],
)
def test_list_deployments_invalid_filters(dm, query, needle):
    c, _ = dm
    resp = c.get(f"/api/v1/deployments?{query}")
    assert resp.status_code == 422
    assert needle in resp.json()["detail"]


def test_create_deployment(dm):
    c, fake = dm
    body = c.post(
        "/api/v1/deployments",
        json={"name": "x", "type": "skill", "target_id": "t", "auto_restart": False},
    ).json()
    assert body["type"] == "skill"
    assert fake.deployed[-1]["name"] == "x"
    assert fake.deployed[-1]["auto_restart"] is False


def test_create_deployment_invalid_type(dm):
    c, _ = dm
    resp = c.post("/api/v1/deployments", json={"type": "nope"})
    assert resp.status_code == 422
    assert "Invalid deployment type" in resp.json()["detail"]


def test_get_deployment_404_and_found(dm):
    c, fake = dm
    assert c.get("/api/v1/deployments/ghost").status_code == 404

    fake.deps["d1"] = _FakeDep()
    body = c.get("/api/v1/deployments/d1").json()
    assert body["id"] == "d1" and body["status"] == "running"


def test_restart_stop_remove(dm):
    c, fake = dm
    fake.deps["d1"] = _FakeDep()

    assert c.post("/api/v1/deployments/d1/restart").json() == {"success": True, "dep_id": "d1"}
    assert c.post("/api/v1/deployments/d1/stop").json() == {"success": True, "dep_id": "d1"}
    assert c.delete("/api/v1/deployments/d1").json() == {"success": True, "dep_id": "d1"}

    assert fake.restarted == ["d1"] and fake.undeployed == ["d1"] and fake.removed == ["d1"]


def test_restart_unknown_returns_false(dm):
    c, _ = dm
    assert c.post("/api/v1/deployments/ghost/restart").json()["success"] is False
