"""Requirements 路由测试（api/routers/requirements.py 覆盖补齐）。

顺带修复 D-16：/requirements/export 默认 format="markdown" 却返回 Unsupported format。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import create_app

_DOC = """# 需求文档

**版本**: 1.2.0
**作者**: 张三

- [ ] 高优先级：登录功能 P0
- [x] 修复支付 bug
"""


@pytest.fixture()
def client(core):
    with TestClient(create_app(core)) as c:
        yield c


# ---------------------------------------------------------------------------
# /requirements/parse
# ---------------------------------------------------------------------------


def test_parse_requires_content(client):
    body = client.post("/api/v1/requirements/parse", json={}).json()
    assert body["status"] == "failed" and "No content" in body["error"]


def test_parse_success(client):
    body = client.post("/api/v1/requirements/parse", json={"content": _DOC}).json()
    assert body["status"] == "success"
    assert body["document"]["title"] == "需求文档"
    assert body["document"]["version"] == "1.2.0"
    assert body["document"]["item_count"] == 2
    items = {i["title"]: i for i in body["items"]}
    assert items["高优先级：登录功能 P0"]["priority"] == "high"


def test_parse_truncates_long_description(client):
    long_title = "标题" + "x" * 300
    body = client.post(
        "/api/v1/requirements/parse", json={"content": f"# T\n\n- [ ] {long_title}\n"}
    ).json()
    assert body["items"][0]["description"].endswith("...")


# ---------------------------------------------------------------------------
# /requirements/import
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.updated: list[tuple[str, dict]] = []

    def create_task(self, task_id, payload):
        self.created.append(task_id)

    def update_task(self, task_id, payload):
        self.updated.append((task_id, payload))


def test_import_requires_content(client):
    body = client.post("/api/v1/requirements/import", json={}).json()
    assert body["status"] == "failed"


def test_import_creates_tasks(client, monkeypatch):
    from more_core.api.routers import requirements as req_router

    store = _FakeStore()
    monkeypatch.setattr(req_router, "_task_store", store)

    # 注意：body 声明为 dict[str, str]，auto_start 必须传字符串（传 bool 会 422）
    body = client.post(
        "/api/v1/requirements/import", json={"content": _DOC, "auto_start": "false"}
    ).json()
    assert body["status"] == "success"
    assert body["document_title"] == "需求文档"
    assert body["total_requirements"] == 2
    assert set(store.created) == {"REQ-001", "REQ-002"}
    assert store.updated == []  # auto_start=false → 不启动


def test_import_rejects_non_string_auto_start(client):
    """契约记录：body 类型为 dict[str,str]，非字符串字段会被 422 拒绝。"""
    resp = client.post("/api/v1/requirements/import", json={"content": _DOC, "auto_start": False})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /requirements/templates
# ---------------------------------------------------------------------------


def test_templates_listed(client):
    body = client.get("/api/v1/requirements/templates").json()
    ids = {t["id"] for t in body["templates"]}
    assert {"basic", "detailed"} <= ids
    assert all(t["template"] for t in body["templates"])


# ---------------------------------------------------------------------------
# /requirements/validate
# ---------------------------------------------------------------------------


def test_validate_requires_content(client):
    assert client.post("/api/v1/requirements/validate", json={}).json()["status"] == "failed"


def test_validate_flags_missing_items_and_title(client):
    body = client.post("/api/v1/requirements/validate", json={"content": "没有任何列表项"}).json()
    assert body["status"] == "success"
    assert body["valid"] is False
    fields = {i["field"] for i in body["issues"]}
    assert "title" in fields and "items" in fields
    assert body["summary"]["errors"] >= 1


def test_validate_ok_document(client):
    body = client.post("/api/v1/requirements/validate", json={"content": _DOC}).json()
    assert body["valid"] is True
    assert body["summary"]["total_items"] == 2
    assert body["summary"]["info"] >= 1  # 未设置预计时间 → info


# ---------------------------------------------------------------------------
# /requirements/export
# ---------------------------------------------------------------------------


def test_export_default_markdown_works(client):
    """回归 D-16：默认 format 必须可用（此前默认值直接返回 Unsupported format）。"""
    body = client.get("/api/v1/requirements/export/REQ-1").json()
    assert body["status"] == "success"
    assert body["format"] == "markdown"
    assert body["data"].startswith("# Document REQ-1")


def test_export_json(client):
    body = client.get("/api/v1/requirements/export/REQ-1?format=json").json()
    assert body["status"] == "success" and body["format"] == "json"
    assert "items" in body["data"]


def test_export_csv(client):
    body = client.get("/api/v1/requirements/export/REQ-1?format=csv").json()
    assert body["format"] == "csv" and "ID,标题" in body["data"]


def test_export_unsupported_format(client):
    body = client.get("/api/v1/requirements/export/REQ-1?format=xml").json()
    assert body["status"] == "failed"
