"""API integration tests — FastAPI TestClient."""

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from more_core.api.server import create_app
from more_core.core.config import Settings
from more_core.core.import_task import ImportTaskGenerator, ImportTaskDocument
from more_core.runtime.orchestrator import MoRECore


@pytest.fixture
def _core():
    settings = Settings(
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    core = MoRECore(settings)
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]
    return core


@pytest.fixture
def client(_core):
    app = create_app(_core)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def audit_client(tmp_path: Path) -> Iterator[tuple[MoRECore, TestClient]]:
    """TestClient wired to an isolated audit store so reads are deterministic."""
    settings = Settings(
        audit_log_path=str(tmp_path / "audit.jsonl"),
        providers=[],
        fallback_chain=[],
        enable_evolution=False,
        enable_metacognition=False,
        enable_symbolic=True,
    )
    core = MoRECore(settings)
    from conftest import _FakeLLMProvider

    core.llm._providers["fake"] = _FakeLLMProvider()
    core.llm._fallback = ["fake"]
    app = create_app(core)
    with TestClient(app) as c:
        yield core, c


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_contains_status(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "status" in data


class TestTasksEndpoint:
    def test_execute_nlp_task(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "hello", "type": "nlp_task"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code in (200, 422)

    def test_execute_rejects_wrong_key(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "hello", "type": "nlp_task"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 403

    def test_execute_requires_auth_when_key_set(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "hello", "type": "nlp_task"},
        )
        assert resp.status_code == 401

    def test_execute_works_without_key_env(self, client):
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "hello", "type": "nlp_task"},
        )
        assert resp.status_code in (200, 422)

    def test_execute_auto_type_is_accepted(self, client):
        """'auto' is a valid TaskType and resolves to a concrete type."""
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "开发电话拨号程序APP", "type": "auto"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["metadata"]["auto_resolved_type"] == "code_generation"
        assert data["metadata"]["auto_confidence"] >= 0.6

    def test_execute_auto_falls_back_to_nlp(self, client):
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "你好，随便聊聊", "type": "auto"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["metadata"]["auto_resolved_type"] == "nlp_task"

    def test_execute_path_traversal_blocked(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.post(
            "/api/v1/tasks/execute",
            json={"query": "Read /etc/passwd", "type": "nlp_task"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert "root:" not in resp.text


class TestImportTaskDocumentAPI:
    """ITD endpoint integration tests."""

    def _sample_itd(self) -> str:
        doc = ImportTaskDocument(
            title="API Test Task",
            version="1.0.0",
            author="test",
            created="2026-07-23T00:00:00Z",
            type="code_generation",
            priority="medium",
            deliverable_kind="code",
            tags=["test"],
            summary="A sample ITD for API testing",
        )
        return ImportTaskGenerator().generate(doc)

    def test_get_templates(self, client):
        resp = client.get("/api/v1/tasks/itd/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["templates"]) == 3

    def test_parse_valid_itd(self, client):
        resp = client.post("/api/v1/tasks/itd/parse", json={"content": self._sample_itd()})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["document"]["metadata"]["title"] == "API Test Task"

    def test_parse_empty_returns_error(self, client):
        resp = client.post("/api/v1/tasks/itd/parse", json={"content": ""})
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_validate_itd(self, client):
        resp = client.post("/api/v1/tasks/itd/validate", json={"content": self._sample_itd()})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert "issues" in data
        assert "summary" in data

    def test_generate_itd(self, client):
        resp = client.post(
            "/api/v1/tasks/itd/generate",
            json={
                "title": "Gen Task",
                "version": "1.0.0",
                "author": "test",
                "type": "code_generation",
                "priority": "low",
                "deliverable_kind": "code",
                "summary": "Generated from API",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "title: Gen Task" in data["markdown"]

    def test_templates_have_code_and_architecture_and_analysis(self, client):
        resp = client.get("/api/v1/tasks/itd/templates")
        ids = [t["id"] for t in resp.json()["templates"]]
        assert "code" in ids
        assert "architecture" in ids
        assert "analysis" in ids


class TestAPIAuth:
    def test_health_requires_key_when_set(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.get("/api/v1/health")
        assert resp.status_code == 401
        resp = client.get(
            "/api/v1/health",
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200

    def test_sensitive_read_endpoints_require_key(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        for path in [
            "/api/v1/tasks/history",
            "/api/v1/projects/outputs",
            "/api/v1/llm/state",
            "/api/v1/security/audit",
            "/api/v1/workflows",
            "/api/v1/skills",
        ]:
            resp = client.get(path)
            assert resp.status_code in (401, 403), f"{path} should be auth-gated"

    def test_sensitive_read_endpoints_work_with_key(self, client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        resp = client.get(
            "/api/v1/llm/state",
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200

    def test_create_app_warns_when_no_api_key(self, _core, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            create_app(_core)
        assert any("UNAUTHENTICATED" in r.message for r in caplog.records)

    def test_create_app_no_warning_when_key_set(self, _core, caplog, monkeypatch):
        import logging

        monkeypatch.setenv("MORE_API_KEY", "x")
        with caplog.at_level(logging.WARNING):
            create_app(_core)
        assert not any("UNAUTHENTICATED" in r.message for r in caplog.records)


class TestAuditEndpoint:
    def test_audit_logs_returns_records_with_expected_fields(
        self,
        audit_client: tuple[MoRECore, TestClient],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        core, client = audit_client

        core.audit.log(
            actor="alice",
            action="execute",
            entity="task_abc123",
            layer="L3",
            status="success",
        )
        core.audit.log(
            actor="system",
            action="evolve",
            entity="agent_xyz",
            branch="main",
            score=0.85,
        )
        core.audit.flush()

        resp = client.get(
            "/api/v1/security/audit?limit=2",
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["records"]) == 2

        expected_fields = {"id", "timestamp", "actor", "action", "entity", "payload"}
        for record in data["records"]:
            assert expected_fields.issubset(record.keys())
            assert isinstance(record["timestamp"], float)
            assert isinstance(record["payload"], dict)

        written = {(r["actor"], r["action"], r["entity"]) for r in data["records"]}
        assert written == {
            ("alice", "execute", "task_abc123"),
            ("system", "evolve", "agent_xyz"),
        }

    def test_audit_logs_auth_gated_with_key(self, audit_client, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "test-key-123")
        _, client = audit_client
        resp = client.get("/api/v1/security/audit")
        assert resp.status_code == 401
        resp = client.get(
            "/api/v1/security/audit",
            headers={"Authorization": "Bearer test-key-123"},
        )
        assert resp.status_code == 200


class TestRBACPermission:
    def test_require_permission_honors_x_user_id_header(self):
        import asyncio

        from more_core.security.rbac import (
            Permission,
            UnifiedRBAC,
            require_permission,
            set_rbac_instance,
        )

        set_rbac_instance(UnifiedRBAC(admin_users=["alice"]))
        try:
            checker = require_permission(Permission.SYS_ADMIN)
            asyncio.run(checker(x_user_id="alice"))  # admin passes

            with pytest.raises(PermissionError):
                asyncio.run(checker(x_user_id=None))  # anonymous denied
        finally:
            set_rbac_instance(None)

    def test_require_permission_dev_mode_allows_anonymous(self):
        import asyncio

        from more_core.security.rbac import (
            Permission,
            UnifiedRBAC,
            require_permission,
            set_rbac_instance,
        )

        set_rbac_instance(UnifiedRBAC(admin_users=[]))
        try:
            checker = require_permission(Permission.SYS_ADMIN)
            asyncio.run(checker(x_user_id=None))  # dev mode: no exception
        finally:
            set_rbac_instance(None)
