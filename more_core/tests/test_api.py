"""API integration tests — FastAPI TestClient."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from more_core.api.server import create_app
from more_core.core.config import Settings
from more_core.core.import_task import ImportTaskGenerator, ImportTaskDocument, ResourceBudget
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

    def test_path_traversal_blocked(self, client, monkeypatch):
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
        resp = client.post("/api/v1/tasks/itd/generate", json={
            "title": "Gen Task",
            "version": "1.0.0",
            "author": "test",
            "type": "code_generation",
            "priority": "low",
            "deliverable_kind": "code",
            "summary": "Generated from API",
        })
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
