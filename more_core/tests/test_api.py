"""API integration tests — FastAPI TestClient."""

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from more_core.api.server import (
    API_KEY_MIN_LENGTH,
    API_KEY_PREFIX,
    APIKeyConfigError,
    create_app,
    validate_api_key,
)
from more_core.core.config import Settings
from more_core.core.import_task import ImportTaskDocument, ImportTaskGenerator
from more_core.runtime.orchestrator import MoRECore


@pytest.fixture(autouse=True)
def _ensure_clean_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 API 鉴权环境变量，避免继承宿主机 MORE_API_KEY 影响不期望鉴权的用例。

    背景：T12 向后兼容套件原本通过 monkeypatch.setenv / delenv 单独标记用例；
    若宿主机 MORE_API_KEY 已在进程启动时注入，则未显式声明 monkeypatch 的用例
    会继承该值，导致 create_app() 开启 Bearer 401 屏障，所有『未带 token 期望 200』
    用例均以 401 失败。此 autouse 强制每个测试前置清空两变量，保证用例间相互隔离，
    需要开启鉴权的用例仍用 monkeypatch.setenv 覆盖即可。"""
    monkeypatch.delenv("MORE_API_KEY", raising=False)
    monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)


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


class TestValidateApiKey:
    """Startup validation for MORE_API_KEY — dev mode vs strict mode."""

    def test_returns_empty_and_warns_when_unset(self, monkeypatch, caplog):
        import logging

        monkeypatch.delenv("MORE_API_KEY", raising=False)
        monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)
        with caplog.at_level(logging.WARNING):
            assert validate_api_key() == ""
        assert any("UNAUTHENTICATED" in r.message for r in caplog.records)

    def test_returns_stripped_key(self, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "  sk-more-os-abcdefghijklmn  ")
        assert validate_api_key() == "sk-more-os-abcdefghijklmn"

    def test_whitespace_only_key_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "   ")
        monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)
        assert validate_api_key() == ""

    def test_short_key_warns_but_does_not_raise_in_dev_mode(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("MORE_API_KEY", "short")
        monkeypatch.delenv("MORE_REQUIRE_API_KEY", raising=False)
        with caplog.at_level(logging.WARNING):
            assert validate_api_key() == "short"
        assert any("too short" in r.message for r in caplog.records)

    def test_strict_mode_raises_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("MORE_API_KEY", raising=False)
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        with pytest.raises(APIKeyConfigError, match="not set"):
            validate_api_key()

    def test_strict_mode_raises_when_key_too_short(self, monkeypatch):
        monkeypatch.setenv("MORE_API_KEY", "sk-more-os-abc")
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        with pytest.raises(APIKeyConfigError, match="too short"):
            validate_api_key()

    def test_strict_mode_raises_when_prefix_missing(self, monkeypatch):
        key = "z" * (API_KEY_MIN_LENGTH + 4)
        monkeypatch.setenv("MORE_API_KEY", key)
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        with pytest.raises(APIKeyConfigError, match=API_KEY_PREFIX):
            validate_api_key()

    def test_strict_mode_accepts_well_formed_key(self, monkeypatch):
        key = API_KEY_PREFIX + "a" * (API_KEY_MIN_LENGTH + 4)
        monkeypatch.setenv("MORE_API_KEY", key)
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        assert validate_api_key() == key

    def test_explicit_require_overrides_env(self, monkeypatch):
        """require=False must downgrade strict mode even when env says 1."""
        monkeypatch.delenv("MORE_API_KEY", raising=False)
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        assert validate_api_key(require=False) == ""

    def test_create_app_propagates_strict_mode_failure(self, _core, monkeypatch):
        monkeypatch.delenv("MORE_API_KEY", raising=False)
        monkeypatch.setenv("MORE_REQUIRE_API_KEY", "1")
        with pytest.raises(APIKeyConfigError):
            create_app(_core)

    def test_min_length_constant_is_sane(self):
        assert API_KEY_MIN_LENGTH >= 16
        assert API_KEY_PREFIX == "sk-more-os-"


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
